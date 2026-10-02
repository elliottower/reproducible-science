/** The research project a session is working in: its folder, or null before one is touched. */
export type WorkingProject = string | null

declare module 'claude-code' {
  interface PluginState {
    'repro-gates': {
      project: WorkingProject
      /** Whether the person named that project, so the tools' paths no longer move it. */
      isPinned: boolean
      /** The index of the first project the picker's window shows. */
      top: number
      /** How many projects the picker's window shows. */
      windowRows: number
    }
  }
}
