import test from 'node:test';
import assert from 'node:assert/strict';
import Guard from '../automation-guard.mjs';

test('independent hook denies alternate tools regardless of native approval', async () => {
  const guard = await Guard();
  for (const tool of ['bash', 'task', 'edit', 'write', 'playwright_browser_run_code',
      'playwright_browser_type', 'aioffice_office_edit', 'local_speech', 'unknown_mcp']) {
    await assert.rejects(guard['tool.execute.before']({tool}), /prohibited/);
  }
  for (const tool of ['read', 'glob', 'grep', 'scoped_automation_begin',
      'scoped_desktop_folder', 'scoped_external_reason', 'scoped_automation_stop']) {
    await guard['tool.execute.before']({tool});
  }
});
