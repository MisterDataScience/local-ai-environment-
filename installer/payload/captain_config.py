"""One shared text profile for the captain and all temporary workers."""
import copy

DEFAULTS = {'enabled': True, 'model_id': 'local-ai-captain', 'max_workers': 5,
            'max_tasks_per_turn': 12, 'normal_parallel': 2, 'max_parallel': 5,
            'provider': 'ollama', 'single_model': False}


def settings(config):
    value = config.get('captain', {'enabled': False})
    if not isinstance(value, dict) or type(value.get('enabled', False)) is not bool:
        raise ValueError('captain.enabled must be a boolean')
    result = {**DEFAULTS, **value}
    for name, maximum in [('max_workers', 5), ('max_tasks_per_turn', 24),
                          ('normal_parallel', 5), ('max_parallel', 5)]:
        if type(result[name]) is not int or not 1 <= result[name] <= maximum:
            raise ValueError('Invalid captain limit: ' + name)
    if result['normal_parallel'] > result['max_parallel'] or result['max_parallel'] > result['max_workers']:
        raise ValueError('Captain parallel limits must fit its worker pool')
    if result['provider'] not in {'ollama', 'llama'}:
        raise ValueError('Captain provider must be ollama or llama')
    if type(result['single_model']) is not bool:
        raise ValueError('captain.single_model must be a boolean')
    if not isinstance(result['model_id'], str) or not result['model_id'].startswith('local-ai'):
        raise ValueError('Captain must select a local-ai profile')
    if result['enabled'] and result['model_id'] not in config.get('text_models', {}):
        raise ValueError('Captain shared model profile is missing')
    if result['enabled'] and config['text_models'][result['model_id']]['num_ctx'] > 16384:
        raise ValueError('Shared captain contexts are capped at 16K per request')
    return result


def upgrade(config):
    result = copy.deepcopy(config)
    if 'captain' not in result:
        coordinator = result.get('model_team', {}).get('roles', {}).get('coordinator', 'local-ai')
        if result.get('model_team', {}).get('enabled') and coordinator in result.get('text_models', {}):
            result['text_models']['local-ai-captain'] = copy.deepcopy(result['text_models'][coordinator])
            result['text_models']['local-ai-captain'].update(name='Captain · shared local team', num_ctx=8192)
            result['captain'] = copy.deepcopy(DEFAULTS)
        else:
            result['captain'] = {'enabled': False}
    settings(result)
    return result
