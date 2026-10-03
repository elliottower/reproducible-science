/** The research project a session is working in: its folder, or null before one is touched. */
export type WorkingProject = string | null

declare module 'claude-code' {
  interface PluginState {
    'repro': {
      project: WorkingProject
      /** Whether the person named that project, so the tools' paths no longer move it. */
      isPinned: boolean
      /** The index of the first project the picker's window shows. */
      top: number
      /** How many projects the picker's window shows. */
      windowRows: number
      /** The readout drawn in the band above the prompt. */
      statusLine: string
      /** The last full quotation check of each project, as `found/pinned found`, by folder. */
      quotations: Record<string, string>
    }
  }
}
