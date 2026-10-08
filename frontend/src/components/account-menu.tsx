import { SignInButton, UserButton } from "@clerk/nextjs";
import Link from "next/link";
import { clerkEnabled, currentUserId } from "@/lib/auth";

/** Header controls: sign in, or settings and the account menu. Nothing without accounts. */
export async function AccountMenu() {
  if (!clerkEnabled) return null;
  if (!(await currentUserId())) {
    return (
      <SignInButton mode="modal">
        <button className="rounded-md bg-accent px-3 py-1 text-xs font-semibold text-accent-ink">Sign in</button>
      </SignInButton>
    );
  }
  return (
    <>
      <Link href="/settings" className="text-xs text-ink-2 hover:text-ink">
        Settings
      </Link>
      <UserButton />
    </>
  );
}
