/** Feature flags, configured per deployment through VITE_FLAGS="flag-a,flag-b". */
export type FlagName = 'room-search' | 'room-schedule' | 'self-check-in';

const enabled = new Set(
  String(import.meta.env.VITE_FLAGS ?? '')
    .split(',')
    .map((flag) => flag.trim())
    .filter(Boolean),
);

export const flags = {
  isEnabled(name: FlagName): boolean {
    return enabled.has(name);
  },
};
