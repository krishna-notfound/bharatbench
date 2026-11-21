import { WelcomeHero } from "@/components/welcome/welcome-hero";
import { RecentSessions } from "@/components/welcome/recent-sessions";

export default function Home() {
  return (
    <div className="space-y-14 py-8 md:space-y-20 md:py-16">
      <WelcomeHero />
      <RecentSessions />
    </div>
  );
}
