"""Versioned local team. Context targets are limits, not hardware benchmarks."""
import copy

QWEN4 = 'huihui_ai/qwen3.5-abliterated:4B'
QWEN9 = 'huihui_ai/qwen3.5-abliterated:9b'
CODER = 'local-ai-gemma4-coder:q4-k-m-v1'
CODER_FILE = 'Huihui-gemma-4-12B-coder-fable5-composer2.5-v1-abliterated.Q4_K_M.gguf'
CODER_URL = ('https://huggingface.co/mradermacher/'
             'Huihui-gemma-4-12B-coder-fable5-composer2.5-v1-abliterated-GGUF/resolve/main/' + CODER_FILE)
CODER_SHA256 = '8cecd45f3f353f6d799ca5104533e8bd39944679712e6ca119d5697efc14d552'
# Published registry manifest identifiers. Installation records the full digest
# and refuses a moving tag whose published identifier no longer matches.
REGISTRY_DIGESTS = {QWEN4: '9acbd90c2645', QWEN9: '92a443adb124'}
PROFILES = {
    'coordinator': (QWEN4, 8192),
    'document': (QWEN4, 32768),
    'analyst': (QWEN9, 32768),
    'coder': (CODER, 16384),
}


def preset(role):
    model, context = PROFILES[role]
    return {'name': role.title() + ' · ' + ('Qwen3.5 4B' if role in ('coordinator', 'document')
            else 'Qwen3.5 9B' if role == 'analyst' else 'Gemma4 12B Coder'),
            'model': model, 'num_ctx': context, 'keep_alive_seconds': 120,
            'thinking': False, 'role': role}


def valid_profile(value):
    role = value.get('role')
    return role in PROFILES and value.get('model') == PROFILES[role][0]


def upgrade_team(config):
    """Replace only unchanged stock presets. Custom entries keep their identity."""
    from text_models import DEFAULT_TEXT_MODELS, configured_text_models
    result = copy.deepcopy(config)
    if result.get('model_team_version', 0) >= 1:
        configured_text_models(result)
        return result
    models = result['text_models']
    roles = {}
    for role, old_id in [('coordinator', 'local-ai'), ('analyst', 'local-ai-large')]:
        old = models.get(old_id)
        stock = DEFAULT_TEXT_MODELS[old_id]
        if old and old['model'] == stock['model'] and old['num_ctx'] == stock['num_ctx'] and not old.get('thinking'):
            replacement = preset(role)
            replacement['keep_alive_seconds'] = old['keep_alive_seconds']
            models[old_id] = replacement
            roles[role] = old_id
        else:
            identifier = 'local-ai-team-' + role
            if identifier in models:
                raise ValueError('Reserved model team ID already exists: ' + identifier)
            models[identifier] = preset(role)
            roles[role] = identifier
    old = models.get('local-ai-small')
    if old and old['model'] == DEFAULT_TEXT_MODELS['local-ai-small']['model'] and old['num_ctx'] == 16384 and not old.get('thinking'):
        replacement = preset('coordinator')
        replacement['keep_alive_seconds'] = old['keep_alive_seconds']
        models['local-ai-small'] = replacement
    for role in ('document', 'coder'):
        identifier = 'local-ai-team-' + role
        if identifier in models:
            raise ValueError('Reserved model team ID already exists: ' + identifier)
        models[identifier] = preset(role)
        roles[role] = identifier
    result['model_team_version'] = 1
    result['model_team'] = {'enabled': True, 'roles': roles}
    configured_text_models(result)
    return result


def team_roles(config, visible):
    team = config.get('model_team', {})
    if not team.get('enabled', False):
        return {}
    models = config['text_models']
    captain = config.get('captain', {})
    if captain.get('enabled') and captain.get('single_model'):
        identifier = captain.get('model_id')
        if identifier not in visible or identifier not in models:
            raise ValueError('Shared captain role unavailable')
        shared = {role: identifier for role in ('coordinator', 'document', 'analyst', 'coder')}
        document = team.get('roles', {}).get('document')
        if document in visible and valid_profile(models.get(document, {})) and models[document].get('role') == 'document':
            # Preserve the existing 32K essay/scaffold contract profile. It reuses
            # the 4B Gaming fallback weights and executes through the serial path.
            shared['document'] = document
        return shared
    roles = team.get('roles', {})
    for role in ('coordinator', 'document', 'analyst', 'coder'):
        identifier = roles.get(role)
        value = models.get(identifier, {})
        if identifier not in visible or not valid_profile(value) or value.get('role') != role:
            raise ValueError('Model team role unavailable: ' + role)
    return roles
