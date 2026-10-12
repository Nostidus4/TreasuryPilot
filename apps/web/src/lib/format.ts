import {
  differenceInCalendarDays,
  format,
  formatDistanceToNowStrict,
} from 'date-fns';

export function formatDate(iso: string): string {
  return format(new Date(iso), 'MMM d, yyyy');
}

export function formatDateTime(iso: string): string {
  return format(new Date(iso), 'MMM d, HH:mm');
}

export function formatTime(iso: string): string {
  return format(new Date(iso), 'HH:mm:ss');
}

export function formatRelative(iso: string): string {
  return formatDistanceToNowStrict(new Date(iso), { addSuffix: true });
}

/** "Due in 3 days", "Due today", "Overdue by 2 days". */
export function dueLabel(
  iso: string,
  now = new Date(),
): {
  text: string;
  overdue: boolean;
  soon: boolean;
} {
  const days = differenceInCalendarDays(new Date(iso), now);
  if (days < 0) {
    return {
      text: `Overdue by ${-days} day${days === -1 ? '' : 's'}`,
      overdue: true,
      soon: true,
    };
  }
  if (days === 0) return { text: 'Due today', overdue: false, soon: true };
  return {
    text: `Due in ${days} day${days === 1 ? '' : 's'}`,
    overdue: false,
    soon: days <= 3,
  };
}

export function shortAddress(address: string): string {
  return address.length > 12
    ? `${address.slice(0, 6)}…${address.slice(-4)}`
    : address;
}

export function shortHash(hash: string): string {
  return hash.length > 16 ? `${hash.slice(0, 10)}…${hash.slice(-6)}` : hash;
}

export function countdown(until: string, now = Date.now()): string | null {
  const ms = new Date(until).getTime() - now;
  if (ms <= 0) return null;
  const totalMinutes = Math.floor(ms / 60_000);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours >= 24) return `${Math.floor(hours / 24)}d ${hours % 24}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  if (minutes > 0) return `${minutes}m`;
  return `${Math.ceil(ms / 1000)}s`;
}
