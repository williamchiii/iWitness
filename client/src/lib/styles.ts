// Outlined pill button, shared by the header and the camera pane.
export const OUTLINE_PILL =
  'shrink-0 rounded-full border border-ink/15 px-5 py-2 text-sm font-medium transition-colors hover:bg-white/70'

// Popups (camera, saved clip, delete box) fade and rise in, and fade and sink
// out. `starting:` is where they enter from; the *_OUT classes are where they
// leave to, applied while usePopupExit() waits out the 200 ms before unmounting.
export const POPUP_BACKDROP = 'transition-opacity duration-200 ease-out starting:opacity-0 motion-reduce:transition-none'
export const POPUP_BACKDROP_OUT = 'pointer-events-none opacity-0'
export const POPUP_PANEL = 'transition duration-200 ease-out starting:translate-y-3 starting:scale-[0.98] motion-reduce:transition-none'
export const POPUP_PANEL_OUT = 'translate-y-3 scale-[0.98]'
