/** Unique browser IDs also work on HTTP deployments where randomUUID is absent. */
export function clientId(): string {
  return Array.from(crypto.getRandomValues(new Uint32Array(4)),
    value => value.toString(16).padStart(8, '0')).join('')
}
