import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from 'react'

/** One line at the foot of the page, for a moment: what a click did, or why it could not. */
const ToastCtx = createContext<(text: string) => void>(() => undefined)
export const useToast = () => useContext(ToastCtx)

export function ToastHost({ children }: { children: ReactNode }) {
  const [text, setText] = useState<string | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const show = useCallback((t: string) => {
    setText(t)
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => setText(null), 3200)
  }, [])
  return (
    <ToastCtx.Provider value={show}>
      {children}
      <div className={`toast ${text ? 'on' : ''}`} role="status">{text}</div>
    </ToastCtx.Provider>
  )
}

/** Puts `text` on the clipboard and says `said`, or that it could not. */
export function useCopy() {
  const toast = useToast()
  return (text: string, said: string) =>
    navigator.clipboard.writeText(text).then(() => toast(said), () => toast('Could not copy to the clipboard'))
}
