export function formatTime(at: number): string {
  return new Date(at).toLocaleTimeString("he-IL", { hour: "2-digit", minute: "2-digit" });
}
