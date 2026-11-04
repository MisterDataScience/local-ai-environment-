"""Private, atomic feature receipts and a fail-closed runtime capability view.

Saved owner configuration is never rewritten to hide an unavailable feature.
Only the in-memory runtime view is restricted. Receipts contain no credentials.
"""
from contextlib import contextmanager
import copy
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile

STATES = {'not_installed', 'installed', 'awaiting_user', 'configured', 'testing',
          'ready', 'failed', 'disabled'}
# Ordered for Install Everything; dependencies are never installed implicitly.
FEATURES = {
    'core': ('Install LOCAL AI Core.command', None, ()),
    'workspace': ('Install Encrypted Workspace.command', 'vault', ('core',)),
    'speech': ('Install Local Speech.command', 'speech', ('core',)),
    'conversation': ('Install Live Conversation.command', 'conversation', ('speech',)),
    # Current Discord transport uses the conversation audio bridge, including STT.
    'discord': ('Install Discord Voice.command', 'discord', ('conversation',)),
    'media': ('Install Image and Video.command', 'media_generation', ('core',)),
    'office': ('Install Office Tools.command', 'office', ('core',)),
    'web': ('Install Encrypted Web Access.command', 'web', ('core',)),
    'browser': ('Install Browser Automation.command', 'browser', ('web',)),
    'remote': ('Install Remote Access.command', 'remote_access', ('core',)),
    'github': ('Connect GitHub.command', 'account_tools', ('core',)),
}


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def safe_path(path):
    """Reject link traversal and special files before reading or replacing state."""
    path = Path(path).absolute()
    for item in (path, *path.parents):
        if item.is_symlink():
            raise RuntimeError('Symbolic links are not allowed in installer state paths')
    if path.exists() and not (path.is_file() or path.is_dir()):
        raise RuntimeError('Installer state must use regular files and directories')
    return path


def atomic_json(path, value):
    path = safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.local-ai-')
    try:
        with os.fdopen(fd, 'w') as output:
            json.dump(value, output, indent=2, sort_keys=True)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
        parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def installation_lock(root, *, shared=False):
    path = safe_path(Path(root) / '.installer.lock')
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise RuntimeError('Installer lock must be a regular file')
        try:
            fcntl.flock(fd, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another installer or Local AI runtime is active. Stop it before installing.') from None
        yield
    finally:
        os.close(fd)


def state_path(root, feature):
    if feature not in FEATURES:
        raise ValueError('Unknown LOCAL AI feature')
    return safe_path(Path(root) / 'state/features' / (feature + '.json'))


def read(root, feature):
    path = state_path(root, feature)
    if not path.exists():
        return {'feature': feature, 'status': 'not_installed', 'installer': FEATURES[feature][0]}
    result = json.loads(path.read_text())
    if (not isinstance(result, dict) or result.get('schema') != 1 or
            result.get('feature') != feature or result.get('status') not in STATES):
        raise RuntimeError('Invalid feature receipt: ' + feature)
    return result


def source_signature(root, feature):
    names = ('feature_state.py', 'feature_install.py', 'feature_checks.py',
             {'workspace': 'workspace_setup.py', 'speech': 'voice_setup.py',
              'conversation': 'conversation_setup.py', 'discord': 'discord-adapter.mjs',
              'media': 'model_engine.py', 'office': 'office_setup.py', 'web': 'web_access.py',
              'browser': 'browser_setup.py', 'remote': 'remote_access.py',
              'github': 'account_tools.py', 'core': 'installer.py'}[feature])
    return hashes({name: Path(root) / 'control' / name for name in names})


def write(root, feature, status, **details):
    if status not in STATES:
        raise ValueError('Invalid feature state')
    result = {**read(root, feature), 'schema': 1, 'feature': feature, 'status': status,
              'installer': FEATURES[feature][0], 'dependencies': list(FEATURES[feature][2]),
              'last_check': now(), **details}
    if status == 'ready':
        result['source_hashes'] = source_signature(root, feature)
    atomic_json(state_path(root, feature), result)
    return result


def snapshot(root):
    result = {}
    for feature in FEATURES:
        try:
            result[feature] = read(root, feature)
        except (OSError, ValueError, RuntimeError):
            result[feature] = {'feature': feature, 'status': 'failed', 'installer': FEATURES[feature][0],
                'last_failure': 'InvalidReceipt', 'next_action': 'Repair the private feature receipt, then rerun ' + FEATURES[feature][0]}
    return result


def migrate(root, config):
    """Adopt interrupted/full/trial installs without inventing acceptance passes."""
    for feature, (launcher, key, dependencies) in FEATURES.items():
        if state_path(root, feature).exists():
            continue
        enabled = bool(config.get(key, {}).get('enabled')) if key else False
        if feature == 'github':
            enabled = bool(config.get('account_tools', {}).get('github'))
        write(root, feature, 'configured' if enabled else 'not_installed',
              installed_version=None, validated_hashes={}, last_failure=None,
              next_action=('Run ' + launcher + ' to verify this existing configuration.') if enabled else '')


def available(config, feature):
    """Legacy profiles retain their existing gates until explicitly migrated."""
    if config.get('feature_schema') != 1:
        return True
    return config.get('_feature_status', {}).get(feature) == 'ready'


def effective_config(root, config, *, testing=()):
    if config.get('feature_schema') != 1:
        return copy.deepcopy(config)
    result = copy.deepcopy(config)
    rows = snapshot(root)
    statuses = {name: row['status'] for name, row in rows.items()}
    for name, row in rows.items():
        if row['status'] == 'ready':
            try:
                if row.get('source_hashes') != source_signature(root, name):
                    statuses[name] = 'configured'
            except (OSError, ValueError, RuntimeError):
                statuses[name] = 'failed'
    # Installer-owned subprocesses use this only for bounded native acceptance.
    # It is not persisted or accepted through an HTTP request.
    for name in testing:
        if name not in FEATURES or statuses[name] != 'testing':
            raise RuntimeError('Feature is not in an installer-owned acceptance stage')
        statuses[name] = 'ready'
    # A dependent receipt cannot override a failed or missing prerequisite.
    for name, (_, _, dependencies) in FEATURES.items():
        if statuses[name] == 'ready' and any(statuses[dep] != 'ready' for dep in dependencies):
            statuses[name] = 'configured'
    result['_feature_status'] = statuses
    for name, (_, key, _) in FEATURES.items():
        if not key or available(result, name):
            continue
        if name == 'workspace':
            # Keep the original storage policy: locked/unaccepted vaults must
            # never redirect a sensitive write into plaintext media storage.
            continue
        if name == 'github':
            result.setdefault(key, {})['github'] = False
        else:
            result.setdefault(key, {})['enabled'] = False
    if not available(result, 'remote'):
        result['public_url'] = 'http://127.0.0.1:8001'
    return result


def require(config, feature):
    if not available(config, feature):
        raise ValueError('Capability unavailable (' + feature + '). Run ' + FEATURES[feature][0])


def hashes(paths):
    result = {}
    for label, path in paths.items():
        path = safe_path(path)
        if not path.is_file():
            continue
        digest = hashlib.sha256()
        with path.open('rb') as source:
            while block := source.read(8 * 1024 * 1024):
                digest.update(block)
        result[label] = digest.hexdigest()
    return result


def optional_runtime_config(root, config):
    """Do not let an unavailable optional MCP prevent the Captain from starting."""
    if config.get('feature_schema') != 1:
        return config
    result = copy.deepcopy(config)
    if result.get('web', {}).get('enabled'):
        try:
            from web_access import status
            if status(root).get('status') != 'ready':
                raise RuntimeError('VPN unavailable')
        except (OSError, ValueError, RuntimeError):
            result['web']['enabled'] = False
            result.setdefault('browser', {})['enabled'] = False
            result['_feature_status']['web'] = 'configured'
            result['_feature_status']['browser'] = 'configured'
    if result.get('browser', {}).get('enabled'):
        try:
            from browser_setup import mcp_probe
            if not mcp_probe().get('name'):
                raise RuntimeError('Browser unavailable')
        except (OSError, ValueError, RuntimeError):
            result['browser']['enabled'] = False
            result['_feature_status']['browser'] = 'configured'
    if result.get('office', {}).get('enabled'):
        try:
            from office_setup import verify_binary, binary_path
            verify_binary(binary_path(root))
        except (OSError, ValueError, RuntimeError):
            result['office']['enabled'] = False
            result['_feature_status']['office'] = 'failed'
    return result
