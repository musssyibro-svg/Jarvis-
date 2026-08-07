/**
 * App.jsx — entry point.
 *
 * Jarvis is no longer "an app with tabs". JarvisOS is a single operating console:
 * the status strip, subsystem view, activity timeline and command bar are always
 * live, and everything else renders inside that shell.
 */
import JarvisOS from "./JarvisOS";

export default function App() {
  return <JarvisOS />;
}
