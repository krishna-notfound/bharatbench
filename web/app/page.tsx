import { HomeHero } from "@/components/home/home-hero";
import { RecentSessions } from "@/components/welcome/recent-sessions";

export default function Home() {
  return (
    <div className="space-y-14 py-4 md:space-y-20 md:py-10">
      <HomeHero />
      <RecentSessions />
    </div>
  );
}
