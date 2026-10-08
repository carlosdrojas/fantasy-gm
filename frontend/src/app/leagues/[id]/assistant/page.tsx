import { Chat } from "@/components/chat";
import { api, getHealth } from "@/lib/api";

export default async function AssistantPage({ params }: PageProps<"/leagues/[id]/assistant">) {
  const id = Number((await params).id);
  const [questions, health] = await Promise.all([api.quickQuestions(), getHealth()]);
  return <Chat leagueId={id} questions={questions} needsUserKey={health.assistant_needs_user_key} />;
}
