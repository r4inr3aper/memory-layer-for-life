import type { ReactNode } from "react";

import { AppShell } from "@/components/layout/app-shell";
import { matchPath, useRouteLocation } from "@/lib/router";
import { CallsPage } from "@/pages/calls";
import { EvaluationDetailPage } from "@/pages/evaluation-detail";
import { EvaluationsPage } from "@/pages/evaluations";
import { NotFoundPage } from "@/pages/not-found";
import { OverviewPage } from "@/pages/overview";
import { Phase1Page } from "@/pages/phase1";
import { PipelinePage } from "@/pages/pipeline";
import { PlaygroundPage } from "@/pages/playground";

interface Route {
  pattern: string;
  render: (params: Record<string, string>, search: string) => ReactNode;
}

// A page that shows one record takes its id as a key, so opening another record starts
// the page afresh instead of carrying over what was open.
const ROUTES: Route[] = [
  { pattern: "/", render: () => <OverviewPage /> },
  { pattern: "/playground", render: () => <PlaygroundPage runId={null} /> },
  {
    pattern: "/playground/:runId",
    render: ({ runId }) => <PlaygroundPage runId={runId} />,
  },
  { pattern: "/evaluations", render: () => <EvaluationsPage /> },
  {
    pattern: "/evaluations/:runId",
    render: ({ runId }) => <EvaluationDetailPage key={runId} runId={runId} />,
  },
  // The filters start from the address, so a new address starts the page afresh.
  { pattern: "/calls", render: (_params, search) => <CallsPage key={search} /> },
  { pattern: "/pipeline", render: () => <PipelinePage runId={null} /> },
  { pattern: "/pipeline/:runId", render: ({ runId }) => <PipelinePage runId={runId} /> },
  { pattern: "/phase-1", render: () => <Phase1Page /> },
];

export function App() {
  const { path, query } = useRouteLocation();
  let page: ReactNode = <NotFoundPage />;
  for (const route of ROUTES) {
    const params = matchPath(route.pattern, path);
    if (params !== null) {
      page = route.render(params, query.toString());
      break;
    }
  }
  return <AppShell>{page}</AppShell>;
}
