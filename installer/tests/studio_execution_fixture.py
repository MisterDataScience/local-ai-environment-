"""Authored host receipts for controller tests; no compiler/runtime is exercised."""
import json
import time

from studio_store import archive, atomic, encoded, files, ident, sha
from studio_workbench import Workbench


def seed_execution(store, iid, pid, workflow, assignment, actor, names=('fixture',)):
    build = ident('build')
    digest = sha(archive(files(store.path(pid))))
    with store.db() as cx, cx:
        cx.execute('INSERT INTO studio_builds VALUES(?,?,?,?,?,?,?)',
                   (build, pid, digest, 'cartridge', 'passed', '{}', int(time.time())))
    workbench = Workbench(store)
    tests = []
    for name in names:
        evidence = ident('evidence')
        workbench.write_evidence(dict(institution=iid, project=pid, build=build),
            dict(id=evidence, project=pid, build=build, findings=[], assertions=[], input_sequence=[dict(steps=1,buttons=8)], updated=0))
        tests.append(dict(name=name, passed=True, expected={'0': 1}, evidence=evidence))
    cartridge = dict(format=1, title='Authored fixture', source_sha256=digest,
        wasm='', assets={}, tests=[dict(name=name, expect_metrics={'0': 1}) for name in names])
    path = store.directory/iid.split(':')[1]/'builds'/build.split(':')[1]/'cartridge.json'
    atomic(path, encoded(cartridge).encode())
    identity = dict(id=build, state='passed', source_sha256=digest)
    tests_receipt = dict(build=identity, passed=True, tests=tests)
    run = dict(machine=ident('machine'), build=build, evidence=tests[0]['evidence'],
               ticks=1, steps=1, buttons=8, screen_sha256=sha('authored frame'))
    visual = dict(run, status='pass', image_sent=True, review='Authored visual receipt fixture.', issues=[])
    for kind, payload in [('build', identity), ('tests', tests_receipt), ('run', run), ('visual', visual)]:
        store.record_workflow_execution(iid, workflow, assignment, actor, kind, payload)
    report = dict(workflow=workflow, verdict='verified',
        build=dict(build_id=build, source_digest=digest, build_status='success', runtime_status='loaded', errors=[], resources={}),
        tests=[dict(test_id=test['name'], description='Authored controller fixture.', seed=1, inputs=[dict(steps=1,buttons=8)],
                    expected='fixture', actual='fixture', status='passed', evidence=[test['evidence']]) for test in tests],
        implementation_claims=[], findings=[], unverified_questions=[], explanation='Controller routing fixture; native execution is not represented as tested.')
    return dict(report=report, build=identity, tests=tests_receipt, run=run, visual=visual)
