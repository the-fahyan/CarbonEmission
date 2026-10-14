import { Activity, BarChart3, Briefcase, Cpu, Gauge, Leaf, Presentation } from "lucide-react";
import { useState } from "react";
import DemoWizard, { type Page } from "./components/DemoWizard";
import SimBar from "./components/SimBar";
import { ToastProvider } from "./components/ui";
import { LiveProvider } from "./hooks/useLive";
import Jobs from "./pages/Jobs";
import Logs from "./pages/Logs";
import Overview from "./pages/Overview";
import Scheduling from "./pages/Scheduling";
import TelemetryPage from "./pages/TelemetryPage";

const NAV: { id: Page; label: string; icon: typeof Gauge }[] = [
  { id: "overview", label: "Overview", icon: Gauge }, { id: "jobs", label: "Jobs", icon: Briefcase },
  { id: "telemetry", label: "Telemetry", icon: Activity }, { id: "scheduling", label: "Scheduling", icon: Cpu }, { id: "logs", label: "Logs & analytics", icon: BarChart3 },
];

export default function App() {
  const [page, setPage] = useState<Page>("overview");
  const [demo, setDemo] = useState(false);
  return (
    <ToastProvider><LiveProvider>
      <div className="flex min-h-screen flex-col md:flex-row">
        <nav aria-label="Main" className="border-b border-ink-600 bg-ink-900 p-3 md:w-56 md:border-b-0 md:border-r">
          <div className="mb-4 flex items-center gap-2 px-2 text-leaf-400"><Leaf className="h-5 w-5" /><span className="text-sm font-bold leading-tight">Carbon-Aware<br />Load Optimizer</span></div>
          <ul className="flex gap-1 overflow-x-auto md:flex-col">
            {NAV.map(({ id, label, icon: Icon }) => (
              <li key={id}><button onClick={() => setPage(id)} aria-current={page === id ? "page" : undefined}
                className={`flex w-full items-center gap-2 whitespace-nowrap rounded-lg px-3 py-2 text-sm ${page === id ? "bg-leaf-600/20 text-leaf-400" : "text-slate-300 hover:bg-ink-800"}`}><Icon className="h-4 w-4" />{label}</button></li>))}
          </ul>
          <button className="btn btn-primary mt-4 w-full justify-center" onClick={() => setDemo(true)}><Presentation className="h-4 w-4" />Run Demo</button>
          <p className="mt-4 px-2 text-xs text-slate-500">SDG 13 · Climate Action<br />Prototype with simulated data</p>
        </nav>
        <div className="flex min-w-0 flex-1 flex-col">
          <SimBar />
          <main className="flex-1 p-4 md:p-6">
            {page === "overview" && <Overview />}{page === "jobs" && <Jobs />}{page === "telemetry" && <TelemetryPage />}
            {page === "scheduling" && <Scheduling />}{page === "logs" && <Logs />}
          </main>
        </div>
        {demo && <DemoWizard onNavigate={setPage} onClose={() => setDemo(false)} />}
      </div>
    </LiveProvider></ToastProvider>
  );
}
