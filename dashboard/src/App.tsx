import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import Layout from "./components/Layout";
import Overview from "./pages/Overview";
import Positions from "./pages/Positions";
import Risk from "./pages/Risk";
import Reconciliation from "./pages/Reconciliation";
import Evidence from "./pages/Evidence";
import Events from "./pages/Events";
import Alerts from "./pages/Alerts";
import System from "./pages/System";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Layout />}>
            <Route index element={<Overview />} />
            <Route path="positions" element={<Positions />} />
            <Route path="risk" element={<Risk />} />
            <Route path="reconciliation" element={<Reconciliation />} />
            <Route path="evidence" element={<Evidence />} />
            <Route path="events" element={<Events />} />
            <Route path="alerts" element={<Alerts />} />
            <Route path="system" element={<System />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

export default App;
