import { notFound, redirect } from "next/navigation";
import {
  DeleteAccountButton,
  EspnCookiesForm,
  RemoveCookiesButton,
  RemoveLeagueButton,
} from "@/components/settings-forms";
import { Card, ErrorPanel } from "@/components/ui";
import { ApiError, api, type EspnStatus } from "@/lib/api";
import { clerkEnabled } from "@/lib/auth";

const STATUS: Record<EspnStatus["status"], { label: string; className: string }> = {
  ok: { label: "Working", className: "text-good" },
  unverified: { label: "Saved, not checked yet", className: "text-ink-2" },
  expired: { label: "Expired: ESPN refused them. Paste fresh ones below.", className: "text-critical" },
};

export default async function SettingsPage() {
  if (!clerkEnabled) notFound();
  let me, leagues;
  try {
    [me, leagues] = await Promise.all([api.me(), api.leagues()]);
  } catch (e) {
    return <ErrorPanel message={e instanceof ApiError ? e.message : String(e)} />;
  }
  if (!me.signed_in) redirect("/");
  const mine = leagues.filter((lg) => !lg.is_demo);

  return (
    <div className="max-w-2xl space-y-8">
      <h1 className="text-xl font-semibold">Settings</h1>

      <Card
        title="ESPN cookies"
        subtitle="Private leagues only show to signed-in ESPN accounts, so Fantasy GM reads them with your ESPN session cookies."
      >
        <div className="space-y-4 text-sm">
          <p>
            Status:{" "}
            {me.espn ? (
              <span className={STATUS[me.espn.status].className}>{STATUS[me.espn.status].label}</span>
            ) : (
              <span className="text-ink-2">Not set</span>
            )}
            {me.espn && (
              <>
                {" · "}
                <RemoveCookiesButton />
              </>
            )}
          </p>
          <ol className="list-decimal space-y-1 pl-5 text-ink-2">
            <li>On a computer, sign in at fantasy.espn.com.</li>
            <li>Open developer tools (F12, or ⌥⌘I on a Mac) → Application (Storage in Firefox) → Cookies.</li>
            <li>
              Pick <code>https://fantasy.espn.com</code>, then copy the values of <code>espn_s2</code> and{" "}
              <code>SWID</code>.
            </li>
          </ol>
          {me.can_store_cookies ? (
            <EspnCookiesForm hasCookies={Boolean(me.espn)} />
          ) : (
            <p className="text-critical">This server isn&apos;t set up to store cookies yet.</p>
          )}
          <p className="text-xs text-muted">
            They&apos;re encrypted before they&apos;re stored, used only to read leagues you add (never to change
            anything on ESPN), and deleted when you remove them or your account. ESPN expires them every few weeks;
            we&apos;ll tell you when to paste new ones.
          </p>
        </div>
      </Card>

      <Card title="Your leagues" subtitle={`${me.leagues} of ${me.max_leagues}`}>
        {mine.length === 0 ? (
          <p className="text-sm text-ink-2">None yet.</p>
        ) : (
          <ul className="divide-y divide-line text-sm">
            {mine.map((lg) => (
              <li key={lg.id} className="flex items-center justify-between py-2">
                <span className="text-ink">
                  {lg.name ?? `League ${lg.external_id}`} <span className="text-xs text-muted">{lg.season}</span>
                </span>
                <RemoveLeagueButton leagueId={lg.id} name={lg.name ?? "this league"} />
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title="Delete account" subtitle="Removes your leagues, ESPN cookies and assistant chats, then your login.">
        <DeleteAccountButton />
      </Card>
    </div>
  );
}
