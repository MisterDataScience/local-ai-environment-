"""Real C/Wasm execution; compiler supplied explicitly for native test hosts."""
import base64,json,os,sys,tempfile,unittest
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parents[1]/'payload')]
import village
from studio_store import Store,files
from studio_workbench import Workbench,sandbox
try:import wasmtime
except ImportError:wasmtime=None

@unittest.skipUnless(wasmtime and os.environ.get('STUDIO_TEST_CLANG'),'requires Wasmtime and explicit fixture compiler')
class RuntimeTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup)
  self.s=Store(Path(self.t.name)/'village',lambda p:village.connect(p,test_encrypted=True));self.i=self.s.create('Fixture','Test')['id'];self.p=self.s.ingest(self.i,'C fixture',files(Path(__file__).resolve().parents[1]/'studio_sdk'),{'kind':'fixture'})
  self.w=Workbench(self.s,sys.executable,Path(os.environ['STUDIO_TEST_CLANG']),test_trusted=True);self.addCleanup(self.w.shutdown)
  self.b=self.w.build(self.p['project']);self.assertEqual(self.b['state'],'passed',self.b)
 def test_compiled_c_replay_snapshot_and_export(self):
  self.assertTrue(self.w.tests(self.i,self.b['id'])['passed'])
  m=self.w.create(self.i,self.b['id'])['machine'];a=self.w.machine(self.i,m,'run',steps=10,buttons=8)
  saved=self.w.machine(self.i,m,'snapshot')['saved'];self.w.machine(self.i,m,'run',steps=3,buttons=2)
  restored=self.w.restore(self.i,saved);self.assertEqual(a['state_sha256'],restored['state_sha256']);self.assertEqual(a['screen_sha256'],restored['screen_sha256'])
  self.assertEqual(base64.b64decode(a['png'])[:8],b'\x89PNG\r\n\x1a\n')
  from studio_player import export
  self.assertTrue(export(self.w.cartridge(self.b['id'])[0]).startswith(b'PK'))
  self.assertEqual(len(self.w.measurements['calibration']['samples']),10)
 def test_portable_evidence_tracks_inputs_assertions_and_findings(self):
  created=self.w.create(self.i,self.b['id'],seed=17);machine=created['machine'];eid=created['evidence']
  run=self.w.machine(self.i,machine,'run',steps=7,buttons=8)
  self.assertEqual(run['evidence'],eid)
  path=self.w.evidence_path(self.w.machines[machine],eid)
  record=json.loads(path.read_text())
  self.assertEqual(record['seed'],17);self.assertEqual(record['source_sha256'],self.w.cartridge(self.b['id'])[0]['build_manifest']['source_sha256'])
  self.assertEqual(record['input_sequence'],[{'steps':7,'buttons':8}])
  self.assertEqual(record['observation']['state_sha256'],run['state_sha256'])
  self.assertNotIn('screenshot_png_base64',record)
  self.assertEqual(self.w.add_finding(self.i,self.p['project'],'Observed','The run produced a state hash.',[eid])['saved'],True)
  self.assertEqual(json.loads(path.read_text())['findings'][-1]['category'],'Observed')
  with self.assertRaises(ValueError):self.w.add_finding(self.i,self.p['project'],'Observed','No citation',[])
  tests=self.w.tests(self.i,self.b['id'])
  if tests['tests']:
   evidence=tests['tests'][0]['evidence']
   self.assertTrue(evidence.startswith('evidence:'))
   test_path=self.w.evidence_path(dict(institution=self.i,build=self.b['id']),evidence)
   self.assertTrue(json.loads(test_path.read_text())['assertions'])

 def test_versioned_build_and_save_identity(self):
  cartridge,_=self.w.cartridge(self.b['id']);manifest=cartridge['build_manifest']
  self.assertEqual(manifest['manifest_version'],1);self.assertEqual(manifest['sdk_version'],'1.0.0');self.assertEqual(manifest['sdk_abi_version'],1);self.assertEqual(manifest['save_format_version'],1)
  machine=self.w.create(self.i,self.b['id'])['machine'];saved=self.w.machine(self.i,machine,'snapshot')['saved']
  state=json.loads((self.s.directory/self.i.split(':')[1]/'machines'/(saved.split(':')[1]+'.json')).read_text())
  self.assertEqual(state['envelope_version'],1);self.assertEqual(state['state']['save_format'],1)
  self.assertEqual(state['build_manifest']['source_sha256'],manifest['source_sha256'])
 def test_legacy_save_migration_keeps_original_and_verifies_copy(self):
  machine=self.w.create(self.i,self.b['id'])['machine'];saved=self.w.machine(self.i,machine,'snapshot')['saved']
  path=self.s.directory/self.i.split(':')[1]/'machines'/(saved.split(':')[1]+'.json')
  record=json.loads(path.read_text());record.pop('envelope_version');record.pop('build_manifest')
  record['state'].pop('save_format');record['state'].pop('sdk_abi_version')
  original=json.dumps(record,separators=(',',':')).encode();path.write_bytes(original)
  restored=self.w.restore(self.i,saved);self.assertTrue(restored['machine'])
  kept=self.s.directory/self.i.split(':')[1]/'machines'/'originals'/(saved.split(':')[1]+'.json')
  self.assertEqual(kept.read_bytes(),original)
  migrated=json.loads(path.read_text());self.assertEqual(migrated['state']['save_format'],1)
  self.assertEqual(migrated['state']['sdk_abi_version'],1);self.assertIn('build_manifest',migrated)
 def test_auto_recovery_checkpoint_obeys_quota(self):
  machine=self.w.create(self.i,self.b['id'])['machine']
  def full(iid,extra=0,replace_path=None):raise ValueError('Institution storage budget exhausted')
  self.s.quota=full
  with self.assertRaisesRegex(ValueError,'storage budget exhausted'):
   self.w.machine(self.i,machine,'run',steps=1)
  self.s.quota=lambda iid,extra=0,replace_path=None:None
  self.assertEqual(self.w.machine(self.i,machine,'observe')['ticks'],0)
 def test_scope_withdrawal_and_pause(self):
  m=self.w.create(self.i,self.b['id'])['machine']
  with self.assertRaises(PermissionError):self.w.machine('wrong',m,'observe')
  p=self.s.withdraw(self.i,self.p['source'],'');self.s.withdraw(self.i,self.p['source'],p['digest'],True)
  with self.assertRaises(PermissionError):self.w.machine(self.i,m,'run')
  self.w.pause()
  with self.assertRaises(RuntimeError):self.w.rpc({'operation':'status'})
 def test_fuel_and_no_system_imports(self):
  from studio_runtime import Runtime,Machine
  r=Runtime()
  body='(module (memory (export "memory") 1) (func (export "vm_init") (param i32)) (func (export "vm_update") (param i32) (loop br 0)) (func (export "vm_draw")))'
  m=Machine(r.engine,wasmtime.wat2wasm(body))
  with self.assertRaises(wasmtime.Trap):m.run(1)
  with self.assertRaises(PermissionError):Machine(r.engine,wasmtime.wat2wasm('(module (import "wasi_snapshot_preview1" "proc_exit" (func (param i32))))'))
 def test_ten_machine_limit(self):
  for _ in range(10):self.w.create(self.i,self.b['id'])
  with self.assertRaises(ValueError):self.w.create(self.i,self.b['id'])
 def test_draw_scratch_memory_does_not_change_saved_state(self):
  from studio_runtime import Runtime,Machine
  r=Runtime();code=wasmtime.wat2wasm('(module (memory (export "memory") 1) (func (export "vm_init") (param i32)) (func (export "vm_update") (param i32)) (func (export "vm_draw") (i32.store (i32.const 100) (i32.const 9))))')
  m=Machine(r.engine,code);self.assertEqual(m.state_bytes()[100],0)
  before=m.snapshot();m.run(3);self.assertEqual(before['memory'],m.snapshot()['memory'])
 def test_reusable_c_graphics_render_real_pixels(self):
  source='''#include "village_graphics.h"
static const uint8_t pixels[4]={1,0,0,1};
static const uint32_t palette[256]={0x000000,0xff0000};
static const uint16_t map[1]={0};
static const uint8_t font[768]={[('A'-32)*8]=128};
void vm_init(int seed){vm_metric(7,vm_overlap(0,0,2,2,1,1,2,2));}
void vm_update(int buttons){}
void vm_draw(void){vm_clear(0x0000ff);vm_sprite(pixels,palette,2,2,2,1,1,0,2);vm_tiles(map,1,1,pixels,2,2,2,palette,-10,-10,0);vm_text8(font,"A",20,20,0xffffff);}
'''
  r=self.s.read(self.p['project'],'example.c');self.s.edit(self.p['project'],'example.c',source,r['sha256'])
  b=self.w.build(self.p['project']);self.assertEqual(b['state'],'passed',b)
  result=self.w.create(self.i,b['id']);self.assertEqual(result['metrics']['7'],1)
  from PIL import Image
  import io
  frame=Image.open(io.BytesIO(base64.b64decode(result['png'])))
  self.assertEqual(frame.getpixel((1,1)),(255,0,0,255));self.assertEqual(frame.getpixel((3,1)),(0,0,255,255))
  self.assertEqual(frame.getpixel((10,10)),(255,0,0,255));self.assertEqual(frame.getpixel((20,20)),(255,255,255,255))

class IsolationTests(unittest.TestCase):
 def test_no_unrestricted_production_fallback(self):
  if sys.platform!='darwin':
   with self.assertRaises(RuntimeError):sandbox(['true'],[],Path('/tmp'))
if __name__=='__main__':unittest.main()
