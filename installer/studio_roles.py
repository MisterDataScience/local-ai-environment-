"""Canonical studio role descriptions, action schemas, and permission profiles."""

CORE_STAFF_ROLES = (
    ('lead', 'coder', 'Lead Designer',
     'Own design direction for assigned projects. Prepare design briefs and coordinate with the Lead Developer.'),
    ('design', 'analyst', 'Systems designer',
     'Plan observable tests for rules, simulations and data.'),
    ('review', 'reviewer', 'Playtest reviewer',
     'Independently verify builds and report reproducible evidence.'),
    ('studio-lead', 'analyst', 'Studio Lead',
     'Run the studio, assign design and technical work, and review evidence-backed learning.'),
    ('lead-developer', 'coder', 'Lead Developer',
     'Own technical delivery and coordinate scoped specialist work.'),
)

MAX_SPECIALIST_SUBTASKS = 3

WORKFLOW_ROLES = {
    'planning': ('Lead Designer', 'design'),
    'middle': ('Systems designer', 'test-plan'),
    'implementation': ('Lead Developer', 'delivery'),
    'verification': ('Playtest reviewer', 'test'),
}

OPTIONAL_STAFF_ROLES = (
    ('engine', 'coder', 'Engine specialist',
     'Help with engine structure, portable C, build diagnostics and reproducible tests.'),
)

ACTION_SPECS = {
    'select_project': '{project}',
    'evidence_read': '{evidence_id,start?,limit?}',
    'tree': '{}',
    'read': '{path,start,lines}',
    'search': '{query}',
    'edit': '{path,text,expected}',
    'patch': '{path,old,new,expected}',
    'sdk': '{file?}',
    'reference': '{reference}',
    'knowledge_search': '{query}',
    'source_tree': '{source}',
    'source': '{source,path,start,lines}',
    'build': '{kind:"cartridge"}',
    'tests': '{build}',
    'create_machine': '{build,seed,task?}',
    'run_machine': '{machine,steps:1..600,buttons:0..255}',
    'observe': '{machine}',
    'inspect': '{machine,question}',
    'snapshot': '{machine}',
    'reset': '{machine,seed}',
    'drop': '{machine}',
    'restore': '{saved}',
    'task': '{title,notes,state,task?}',
    'help': '{resident,question}',
    'delegate': '{resident,title,notes,mode}',
    'team_status': '{}',
    'workflow_start': '{title,goal}',
    'workflow_status': '{workflow}',
    'workflow_assign': '{workflow}',
    'workflow_step': '{workflow,title,body,evidence,review_id?}',
    'workflow_verify': '{workflow,verdict,build,tests,findings,unverified_questions,explanation}',
    'workflow_retry': '{workflow,reason}',
    'workflow_close': '{workflow,summary}',
    'workflow_return': '{workflow,reason}',
    'finding': '{category,text,evidence}',
    'propose': '{kind,title,text,evidence}',
    'learn': '{scope,lesson,evidence}',
    'learning_none': '{reason}',
    'note': '{text}',
    'done': '{summary}',
}

_READ = frozenset({
    'evidence_read', 'tree', 'read', 'search', 'reference', 'knowledge_search',
    'source', 'source_tree', 'sdk',
})
_RUN = frozenset({
    'build', 'tests', 'create_machine', 'run_machine', 'observe',
    'snapshot', 'reset', 'drop', 'inspect',
})
WORKFLOW_STEPS = frozenset({
    'workflow_start', 'workflow_status', 'workflow_assign', 'workflow_step',
    'workflow_verify', 'workflow_retry', 'workflow_close', 'workflow_return',
})
ROLE_ACTIONS = {
    'manager': _READ | frozenset({
        'select_project', 'task', 'delegate', 'workflow_start',
        'workflow_status', 'workflow_assign', 'workflow_retry',
        'workflow_close', 'workflow_return', 'help', 'propose', 'note',
        'learning_none', 'done',
    }),
    'design': _READ | frozenset({
        'workflow_step', 'finding', 'note', 'learning_none', 'done',
    }),
    'test-plan': _READ | frozenset({
        'workflow_step', 'finding', 'note', 'learning_none', 'done',
    }),
    'lead-developer': _READ | _RUN | frozenset({
        'edit', 'patch', 'finding', 'task', 'delegate', 'team_status',
        'note', 'propose', 'learn', 'learning_none', 'done',
    }),
    'implementation': _READ | _RUN | frozenset({
        'edit', 'patch', 'finding', 'note', 'learn', 'learning_none', 'done',
    }),
    'analysis': _READ | frozenset({'note', 'learning_none', 'done'}),
    'test': _READ | _RUN | frozenset({
        'workflow_verify', 'note', 'learning_none', 'done',
    }),
    'appointment': frozenset({
        'tree', 'read', 'search', 'edit', 'patch', 'sdk', 'build', 'tests',
        'learn', 'learning_none', 'note', 'done',
    }),
    'adaptation-plan': frozenset({
        'source_tree', 'source', 'sdk', 'knowledge_search', 'done',
    }),
}
ROLE_ACTIONS['work'] = frozenset(ACTION_SPECS)
