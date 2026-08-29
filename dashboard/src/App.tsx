import { useMemo, Suspense, lazy } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import Layout from "./components/Layout";
import Skeleton from "./components/ui/Skeleton";

const Overview = lazy(() => import("./pages/Overview"));
const Positions = lazy(() => import("./pages/Positions"));
const Risk = lazy(() => import("./pages/Risk"));
const Reconciliation = lazy(() => import("./pages/Reconciliation"));
const Evidence = lazy(() => import("./pages/Evidence"));
const Events = lazy(() => import("./pages/Events"));
const Alerts = lazy(() => import("./pages/Alerts"));
const System = lazy(() => import("./pages/System"));

function PageWrapper({ children }: { children: React.ReactNode }) {
  return (
    <Suspense fallback={<Skeleton className="h-8 w-48 rounded" />}>
      {children}
    </Suspense>
  );
}

function App() {
  const queryClient = useMemo(() => new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 5000,
        retry: 1,
        refetchOnWindowFocus: false,
      },
    },
  }), []);
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Layout />}>
            <Route index element={<PageWrapper><Overview /></PageWrapper>} />
            <Route path="positions" element={<PageWrapper><Positions /></PageWrapper>} />
            <Route path="risk" element={<PageWrapper><Risk /></PageWrapper>} />
            <Route path="reconciliation" element={<PageWrapper><Reconciliation /></PageWrapper>} />
            <Route path="evidence" element={<PageWrapper><Evidence /></PageWrapper>} />
            <Route path="events" element={<PageWrapper><Events /></PageWrapper>} />
            <Route path="alerts" element={<PageWrapper><Alerts /></PageWrapper>} />
            <Route path="system" element={<PageWrapper><System /></PageWrapper>} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

export default App;
