import { Outlet } from "react-router-dom";
import { BottomTabBar } from "./BottomTabBar";

export function AppShell() {
  return (
    <div className="min-h-screen bg-background">
      <main className="mx-auto max-w-xl pb-safe-tab">
        <Outlet />
      </main>
      <BottomTabBar />
    </div>
  );
}
