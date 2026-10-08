// Sign-in state for Server Components and route handlers. Accounts are on when Clerk
// keys are set; otherwise the app is single-user and nobody signs in.
import "server-only";
import { auth } from "@clerk/nextjs/server";

export const clerkEnabled = Boolean(process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY && process.env.CLERK_SECRET_KEY);

/** The signed-in user's Clerk id, or null (signed out, or no accounts). */
export async function currentUserId(): Promise<string | null> {
  if (!clerkEnabled) return null;
  return (await auth()).userId;
}

/** `Authorization` header for the backend: the user's short-lived Clerk session token. */
export async function authHeader(): Promise<Record<string, string>> {
  if (!clerkEnabled) return {};
  const token = await (await auth()).getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}
