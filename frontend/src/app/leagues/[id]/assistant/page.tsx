import { Chat } from "@/components/chat";

export default async function AssistantPage({ params }: PageProps<"/leagues/[id]/assistant">) {
  const id = Number((await params).id);
  return <Chat leagueId={id} />;
}
