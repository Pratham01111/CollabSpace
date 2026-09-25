export const STATUSES = ['TODO', 'IN_PROGRESS', 'DONE']

export function statusLabel(status) {
  return status.replace('_', ' ')
}
