import { redirect } from 'react-router'

/**
 * Catch-all fallback — any URL that matches no route lands on the home page.
 * The app deliberately has no redirect-only routes for valid destinations;
 * this is purely the unmatched-URL (404) fallback.
 */
export function loader() {
  return redirect('/')
}

export default function CatchAll() {
  return null
}
