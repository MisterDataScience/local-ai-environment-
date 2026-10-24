"""Real SQLite/ZIP recovery and erasure; the encrypted mount is simulated."""
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from unittest.mock import patch
import sys
sys.path[:0]=[str(Path(__file__).resolve().parents[1])]
import test_vault_backup as backup_tests
import village
import village_memory as memory
import village_storage as storage
import vault_backup as backup


class VillageStorageTests(backup_tests.BackupTests):
    # Reuse the mount fixture without re-running inherited WebUI-only checks.
    def setUp(self):
        super().setUp()
        original=village.secure_root
        self.extra=[patch('vault_tools.mounted_root',self.mounted),patch.object(village,'secure_root',side_effect=lambda root,**kw:original(root,test_encrypted=True))]
        for p in self.extra:p.start()
        self.import_dir=self.root/'import';self.import_dir.mkdir();self.source=self.import_dir/'conversations.json'
        self.source.write_text(json.dumps([dict(id='private-conversation',title='Private fixture',mapping={'a':dict(parent=None,message=dict(id='a',author={'role':'user'},content={'parts':['PRIVATE SYNTHETIC CORPUS']},create_time=1))})]))
        cx=village.connect(self.root/'village')
        self.receipt=village.import_file(cx,self.root/'village',self.source,confirm=True)
        memory.initialize(cx)
        with cx:cx.execute("INSERT INTO library_documents VALUES('doc:derived','Private derived','DERIVED FIXTURE','general','[]','derived','approved',1,'owner')")
        cx.close()

    def tearDown(self):
        for p in reversed(self.extra):p.stop()
        super().tearDown()

    def test_village_snapshot_restore_preserves_raw_source_and_approved_data(self):
        saved=backup.snapshot(self.root,self.config)
        cx=village.connect(self.root/'village')
        with cx:cx.execute("UPDATE library_documents SET markdown='NEWER'")
        cx.close()
        backup.restore(self.root,self.config,saved)
        cx=village.connect(self.root/'village')
        self.assertEqual(cx.execute('SELECT markdown FROM library_documents').fetchone()[0],'DERIVED FIXTURE');cx.close()
        self.assertEqual((self.root/'village/archive'/(self.receipt['sha']+'.json')).read_bytes(),self.source.read_bytes())
        self.assertTrue(list(self.root.glob('village.before-restore-*')))

    def synod_fixture(self):
        from studio_store import Store
        from synod_store import Archive,SYNOD_ID
        store=Store(self.root/'village');archive=Archive(store)
        message=store.add_message(SYNOD_ID,'owner','PRIVATE SYNOD COMMISSION')
        commission=archive.create_commission(store.message(message['id']))
        return store,archive,commission

    def test_synod_snapshot_restores_immutable_records_and_current_specification(self):
        from synod_store import Archive
        store,archive,commission=self.synod_fixture()
        before=archive.verify(commission['studio'])
        saved=backup.snapshot(self.root,self.config)
        with store.db() as cx,cx:archive.append(cx,commission['studio'],commission['id'],'decision','observed','host',dict(note='Later fixture record'))
        backup.restore(self.root,self.config,saved)
        restored=Archive(store)
        self.assertEqual(restored.verify(commission['studio']),before)
        self.assertEqual(restored.view()['commissions'][0]['brief'],'PRIVATE SYNOD COMMISSION')

    def test_whole_village_reset_erases_synod_archive_and_inbox(self):
        store,archive,commission=self.synod_fixture()
        plan=storage.deletion_plan(self.root,self.config,self.receipt['sha'])
        storage.erase(self.root,self.config,self.receipt['sha'],plan['digest'])
        with store.db() as cx:
            self.assertFalse(cx.execute("SELECT name FROM sqlite_master WHERE name='synod_records'").fetchone())
            self.assertEqual(cx.execute('SELECT count(*) FROM studio_messages').fetchone()[0],0)
            self.assertEqual(len(village.status(cx)),5)

    def test_erase_removes_managed_source_derivatives_and_backup_then_blocks_reimport_and_restore(self):
        saved=backup.snapshot(self.root,self.config)
        external=self.root/'external-copy.zip';shutil.copyfile(self.vault/saved,external)
        history=self.root/'work-agent/state/data';history.mkdir(parents=True);(history/'session.db').write_text('DERIVED FIXTURE')
        project=self.root/'work-agent/projects/copy';project.mkdir(parents=True);(project/'report.md').write_text('DERIVED FIXTURE')
        cx=village.connect(self.root/'village')
        pid=village.propose(cx,sid='writer.sensitive',parent='writer.general',role='writer',tags=['sensitive'],instruction='Private derived directions',collections=['general'])['proposal_id']
        village.approve(cx,pid,'owner');village.activate(cx,'writer.sensitive','owner');cx.close()
        plan=storage.deletion_plan(self.root,self.config,self.receipt['sha'])
        result=storage.erase(self.root,self.config,self.receipt['sha'],plan['digest'])
        self.assertEqual(result['state'],'erased')
        self.assertFalse((self.vault/saved).exists());self.assertFalse(history.exists());self.assertFalse(project.exists())
        cx=village.connect(self.root/'village')
        self.assertEqual(cx.execute('SELECT count(*) FROM imports').fetchone()[0],0)
        self.assertEqual(len(village.status(cx)),5)
        self.assertNotIn('writer.sensitive',str(village.status(cx)))
        self.assertEqual(cx.execute('SELECT count(*) FROM library_documents').fetchone()[0],0)
        with self.assertRaises(PermissionError):village.import_file(cx,self.root/'village',self.source,confirm=True)
        cx.close()
        shutil.copyfile(external,self.vault/saved)
        with self.assertRaises(PermissionError):backup.restore(self.root,self.config,saved)
        (self.root/storage.LEDGER).unlink() # clean local disk cannot roll back the vault tombstone
        with self.assertRaises(PermissionError):backup.restore(self.root,self.config,saved)
        self.assertIn(self.receipt['sha'],storage.ledger(self.root)['sources'])

    def test_deletion_interruption_blocks_reads_and_resumes_from_durable_plan(self):
        plan=storage.deletion_plan(self.root,self.config,self.receipt['sha'])
        with patch.object(storage,'sync_ledger',side_effect=RuntimeError('vault locked')):
            with self.assertRaises(RuntimeError):storage.erase(self.root,self.config,self.receipt['sha'],plan['digest'])
        with self.assertRaises(RuntimeError):village.connect(self.root/'village')
        storage.erase(self.root,self.config,self.receipt['sha'],plan['digest'])
        self.assertFalse((self.root/storage.PENDING).exists())
        cx=village.connect(self.root/'village');self.assertEqual(cx.execute('SELECT count(*) FROM messages').fetchone()[0],0);cx.close()

    def test_corrupt_import_can_be_erased_without_manual_database_repair(self):
        (self.root/'village/archive'/(self.receipt['sha']+'.json')).write_text('damaged private export')
        plan=storage.deletion_plan(self.root,self.config,self.receipt['sha'])
        self.assertTrue(plan['corrupt_source_conservative_reset'])
        storage.erase(self.root,self.config,self.receipt['sha'],plan['digest'])
        self.assertFalse((self.root/'village/archive'/(self.receipt['sha']+'.json')).exists())

    def test_corrupt_source_preview_is_stable_across_connection_collection(self):
        import gc
        (self.root/'village/archive'/(self.receipt['sha']+'.json')).write_text('damaged private export')
        first=storage.deletion_plan(self.root,self.config,self.receipt['sha'])
        gc.collect()
        second=storage.deletion_plan(self.root,self.config,self.receipt['sha'])
        self.assertEqual(first['digest'],second['digest'])

    def test_readers_block_recovery_and_stale_preview_cannot_erase_new_data(self):
        cx=village.connect(self.root/'village')
        with self.assertRaises(RuntimeError):backup.snapshot(self.root,self.config)
        cx.close()
        plan=storage.deletion_plan(self.root,self.config,self.receipt['sha'])
        cx=village.connect(self.root/'village')
        with cx:cx.execute("INSERT INTO audit VALUES('new','new','new',1,NULL)")
        cx.close()
        with self.assertRaises(ValueError):storage.erase(self.root,self.config,self.receipt['sha'],plan['digest'])
        self.assertFalse((self.root/storage.PENDING).exists())

    def test_village_only_backup_does_not_replace_unrelated_webui_data(self):
        shutil.rmtree(self.root/'webui/data')
        saved=backup.snapshot(self.root,self.config)
        (self.root/'webui/data').mkdir();(self.root/'webui/data/keep').write_text('keep')
        backup.restore(self.root,self.config,saved)
        self.assertEqual((self.root/'webui/data/keep').read_text(),'keep')

# Inherited fixture methods are not this class's test surface.
for name in list(backup_tests.BackupTests.__dict__):
    if name.startswith('test_') and name not in VillageStorageTests.__dict__:setattr(VillageStorageTests,name,None)
