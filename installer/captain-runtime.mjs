// Shared only by the installed OpenCode policy modules in this process.
// Native session IDs are registered by host code before any worker prompt.
export const workers = new Map();
export const activeCaptains = new Set();
