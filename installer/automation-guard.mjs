// Independent tool boundary for scoped automation sessions. No model-written code.
export const ALLOWED = new Set(['read', 'glob', 'grep',
  'scoped_automation_status', 'scoped_automation_begin', 'scoped_automation_stop',
  'scoped_desktop_activate', 'scoped_desktop_folder', 'scoped_external_reason']);

export default async function AutomationGuard() {
  return {
    async 'tool.execute.before'(input) {
      if (!ALLOWED.has(input.tool)) {
        throw new Error('Scoped automation: tool prohibited. No browser, shell, write or alternate MCP bypass.');
      }
    },
  };
}
