/** Sliding light/dark switch. A real `role="switch"` button so it is
 *  keyboard-operable and announced correctly, not a styled checkbox. */
export default function ThemeToggle({ theme, onToggle }) {
  const dark = theme === 'dark'
  return (
    <button
      type="button"
      className={`theme-toggle${dark ? ' is-dark' : ''}`}
      onClick={onToggle}
      role="switch"
      aria-checked={dark}
      aria-label={dark ? 'Switch to light theme' : 'Switch to dark theme'}
      title={dark ? 'Switch to light theme' : 'Switch to dark theme'}
    >
      <span className="theme-icon theme-sun" aria-hidden="true">☀</span>
      <span className="theme-icon theme-moon" aria-hidden="true">☾</span>
      <span className="theme-knob" aria-hidden="true" />
    </button>
  )
}
