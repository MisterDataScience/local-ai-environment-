"""Install Discord transport and bind one owner/private channel; secrets stay in Keychain."""
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import tarfile
from urllib.request import Request, urlopen
from urllib.error import HTTPError

NODE_VERSION = '24.21.0'
NODE_SHA256 = 'bed7eea5325e1108f32ce5228ddd6a5f0f08a499ee42aa7442aea583702f6057'
SNOWFLAKE = re.compile(r'^[0-9]{15,22}$')
TOKEN = re.compile(r'^[A-Za-z0-9_.-]{20,250}$')
API = 'https://discord.com/api/v10'


def service(root):
    return 'local-ai-discord-' + hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:16]


def read_token(root, app_id):
    if not SNOWFLAKE.fullmatch(app_id): raise ValueError('Invalid Discord application ID')
    result = subprocess.run(['/usr/bin/security', 'find-generic-password', '-s', service(root), '-a', app_id, '-w'],
                            capture_output=True, text=True, timeout=30)
    token = result.stdout.strip()
    if result.returncode or not TOKEN.fullmatch(token):
        raise RuntimeError('Discord token unavailable in Keychain. Run Connect Discord.command on the Mac.')
    return token


def save_token(root, app_id, token):
    if not SNOWFLAKE.fullmatch(app_id) or not TOKEN.fullmatch(token): raise ValueError('Invalid Discord credentials')
    # Interactive security command input avoids putting the secret in process arguments.
    command = f'add-generic-password -U -s {service(root)} -a {app_id} -w {token}\n'
    subprocess.run(['/usr/bin/security', '-i'], input=command, text=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60, check=True)
    if not secrets.compare_digest(read_token(root, app_id), token):
        raise RuntimeError('Keychain did not confirm the stored Discord credential')


def discord(token, path, data=None):
    req = Request(API + path, data=None if data is None else json.dumps(data).encode(),
                  headers={'Authorization': 'Bot ' + token, 'Content-Type': 'application/json',
                           'User-Agent': 'LocalAI-Discord/1.0'})
    try:
        with urlopen(req, timeout=30) as response: return json.load(response)
    except HTTPError as error:
        # Do not expose the request, headers or token through installer exception logs.
        raise RuntimeError(f'Discord setup request failed (HTTP {error.code}). Check the bot token and invite permissions.') from None


def install(root, download, run):
    archive = root / 'downloads' / f'node-v{NODE_VERSION}-darwin-arm64.tar.gz'
    folder = root / 'tools/node' / NODE_VERSION
    node = folder / 'bin/node'
    ready = folder / 'verified-install'
    if not node.is_file() or not ready.is_file():
        download(f'https://nodejs.org/dist/v{NODE_VERSION}/{archive.name}', archive, NODE_SHA256)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != NODE_SHA256:
            raise RuntimeError('Node archive checksum mismatch')
        prefix = f'node-v{NODE_VERSION}-darwin-arm64/'
        with tarfile.open(archive, 'r:gz') as tar:
            total = 0
            for member in tar:
                if member.name == prefix.rstrip('/'): continue
                if not member.name.startswith(prefix): raise RuntimeError('Unexpected Node archive path')
                relative = member.name[len(prefix):]
                if not relative or '..' in Path(relative).parts or Path(relative).is_absolute(): continue
                if relative != 'bin/node' and not relative.startswith('lib/node_modules/npm/'): continue
                if not member.isfile(): continue  # No symlinks or special files are extracted.
                total += member.size
                if total > 512*1024*1024: raise RuntimeError('Oversized Node archive')
                target = folder / relative; target.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(member) as source, target.open('wb') as out: shutil.copyfileobj(source, out)
                target.chmod(0o755 if relative == 'bin/node' else 0o644)
        ready.write_text(NODE_SHA256 + '\n')
    run([node, '--version'])
    engine = root / 'discord-engine'; engine.mkdir(exist_ok=True, mode=0o700)
    for source, target in [('discord-package.json','package.json'), ('discord-package-lock.json','package-lock.json'),
                           ('discord-adapter.mjs','discord-adapter.mjs'), ('discord-core.mjs','discord-core.mjs')]:
        shutil.copy2(root / 'control' / source, engine / target)
    (engine / 'empty-global-npmrc').write_text('')
    env = {k:v for k,v in os.environ.items() if k in {'HOME','PATH','TMPDIR','LANG'}}
    env['PATH'] = str(node.parent) + os.pathsep + env.get('PATH','/usr/bin:/bin')
    run([node, folder / 'lib/node_modules/npm/bin/npm-cli.js', 'ci', '--ignore-scripts', '--no-audit', '--no-fund',
         '--userconfig', '/dev/null', '--globalconfig', engine / 'empty-global-npmrc',
         '--cache', engine / 'cache', '--registry', 'https://registry.npmjs.org'], cwd=engine, env=env)
    # Includes the platform's prebuilt DAVE library and an actual Opus codec operation.
    run([node, engine / 'discord-adapter.mjs', '--check'], cwd=engine, env=env, timeout=60)
    (engine / 'installed.json').write_text(json.dumps({'node':NODE_VERSION,
        'lock_sha256':hashlib.sha256((engine/'package-lock.json').read_bytes()).hexdigest()}, indent=2)+'\n')


def configure(root, force=False):
    path = root / 'control/config.json'; config = json.loads(path.read_text())
    existing = config.get('discord', {})
    if not force and existing.get('enabled') and (root / 'voice-engine/voices/default.json').is_file():
        try:
            read_token(root, existing['application_id'])
            return existing
        except RuntimeError:
            pass
    print('Connect your Discord account to Local AI.')
    print('Open https://discord.com/developers/applications and create an application.')
    print('On its Bot page, turn Public Bot off, then Reset Token. Paste that token below; input is hidden.')
    token = getpass.getpass('Bot token: ').strip()
    if not TOKEN.fullmatch(token): raise ValueError('Expected a Discord bot token')
    me = discord(token, '/users/@me'); app = discord(token, '/oauth2/applications/@me')
    if not me.get('bot') or app.get('team') or not app.get('owner', {}).get('id'):
        raise ValueError('Use a bot application owned by your personal Discord account')
    if app.get('bot_public', True):
        raise ValueError('Turn Public Bot off on the Discord Bot page, then rerun setup')
    owner, bot, app_id = app['owner']['id'], me['id'], app['id']
    for identifier in (owner, bot, app_id):
        if not SNOWFLAKE.fullmatch(identifier): raise ValueError('Unexpected Discord account identifier')
    # Manage Channels is used only by this deterministic setup to create its private voice channel.
    permissions = 16 + 1024 + 2048 + 16384 + 32768 + 65536 + 1048576 + 2097152
    print(f'Open https://discord.com/oauth2/authorize?client_id={app_id}&scope=bot&permissions={permissions}')
    input('Add the bot to a server you own, then press Enter: ')
    guilds = discord(token, '/users/@me/guilds')
    owned = []
    for guild in guilds:
        detail = discord(token, '/guilds/' + guild['id'])
        if detail.get('owner_id') == owner: owned.append(guild)
    if not owned: raise ValueError('The bot must be installed in a server owned by your Discord account')
    if len(owned) == 1: guild = owned[0]
    else:
        for i, item in enumerate(owned, 1): print(f'{i}. {item["name"]}')
        index = int(input('Server number: ')) - 1
        if not 0 <= index < len(owned): raise ValueError('Invalid server selection')
        guild = owned[index]
    save_token(root, app_id, token)
    # Save the channel immediately so a later voice-registration failure cannot create duplicates on resume.
    channel_id = existing.get('channel_id') if existing.get('guild_id') == guild['id'] and existing.get('application_id') == app_id else None
    if not channel_id:
        allow = 1024 + 2048 + 16384 + 32768 + 65536 + 1048576 + 2097152
        channel = discord(token, '/guilds/' + guild['id'] + '/channels', {'name':'local-ai','type':2,
            'permission_overwrites':[{'id':guild['id'],'type':0,'deny':'1024','allow':'0'},
                                    {'id':owner,'type':1,'allow':str(allow),'deny':'0'},
                                    {'id':bot,'type':1,'allow':str(allow),'deny':'0'}]})
        channel_id = channel['id']
    settings = {'enabled':False, 'application_id':app_id, 'owner_id':owner, 'bot_id':bot,
                'guild_id':guild['id'], 'channel_id':channel_id, 'voice':'default'}
    config['discord'] = settings
    def save():
        temporary = path.with_suffix('.discord.tmp'); temporary.write_text(json.dumps(config,indent=2)+'\n')
        temporary.chmod(0o600); temporary.replace(path)
    save()
    if not (root / 'voice-engine/voices/default.json').is_file():
        from voice_setup import register
        print('Register your voice once. Use a clean 3–30 second, 16-bit PCM WAV recording.')
        sample = input('Reference WAV path: ').strip()
        transcript = input('Exact words spoken in that recording: ').strip()
        register(root, 'default', sample, transcript)
    settings['enabled'] = True; save()
    print('Discord connected. Join the private local-ai voice channel while Local AI is running.')
    return settings


if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--root',type=Path,required=True)
    args=parser.parse_args()
    try: configure(args.root.expanduser().resolve(), force=True)
    except Exception as error: raise SystemExit('Discord setup stopped: '+str(error))
