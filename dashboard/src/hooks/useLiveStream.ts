import { useEffect, useRef, useState, useCallback } from "react";
import type { Account, Position, HealthState, RiskState, Alert } from "../lib/api";

interface LiveState {
  account: Account | null;
  positions: Position[];
  health: HealthState | null;
  risk: RiskState | null;
  alerts: Alert[];
}

interface UseLiveStreamReturn {
  state: LiveState;
  connected: boolean;
  lastUpdate: Date | null;
  error: string | null;
}

const WS_URL = `ws://${window.location.hostname}:8080/ws/live`;
const RECONNECT_DELAY = 3000;
const MAX_RECONNECT_DELAY = 30000;

export function useLiveStream(): UseLiveStreamReturn {
  const [state, setState] = useState<LiveState>({
    account: null,
    positions: [],
    health: null,
    risk: null,
    alerts: [],
  });
  const [connected, setConnected] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectDelayRef = useRef(RECONNECT_DELAY);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    try {
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        setError(null);
        reconnectDelayRef.current = RECONNECT_DELAY;
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);

          if (msg.type === "state_update" && msg.data) {
            setState({
              account: msg.data.account || null,
              positions: msg.data.positions || [],
              health: msg.data.health || null,
              risk: msg.data.risk || null,
              alerts: msg.data.alerts || [],
            });
            setLastUpdate(new Date());
          }
        } catch {
          // Ignore parse errors
        }
      };

      ws.onclose = () => {
        setConnected(false);
        scheduleReconnect();
      };

      ws.onerror = () => {
        setConnected(false);
        setError("WebSocket connection error");
        ws.close();
      };
    } catch (err) {
      setError(`Failed to connect: ${err}`);
      scheduleReconnect();
    }
  }, []);

  const scheduleReconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
    }

    reconnectTimeoutRef.current = setTimeout(() => {
      reconnectDelayRef.current = Math.min(
        reconnectDelayRef.current * 2,
        MAX_RECONNECT_DELAY
      );
      connect();
    }, reconnectDelayRef.current);
  }, [connect]);

  useEffect(() => {
    connect();

    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [connect]);

  return { state, connected, lastUpdate, error };
}
