/**
 * Finoks WebSocket hook — Strict Mode safe with exponential reconnect.
 */

import { useEffect, useRef, useState } from "react";
import { buildWsUrl } from "../api/client.js";

const MAX_BACKOFF_MS = 30_000;

export function useAgentSocket(onMessage) {
  const [connected, setConnected] = useState(false);
  const [lastMessageAt, setLastMessageAt] = useState(null);
  const wsRef = useRef(null);
  const activeRef = useRef(true);
  const handlerRef = useRef(onMessage);
  const reconnectTimerRef = useRef(null);
  const attemptRef = useRef(0);

  useEffect(() => {
    handlerRef.current = onMessage;
  }, [onMessage]);

  useEffect(() => {
    activeRef.current = true;
    let initialConnectTimer = null;

    function clearReconnect() {
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
    }

    function scheduleReconnect() {
      if (!activeRef.current) return;
      const wait = Math.min(MAX_BACKOFF_MS, 1000 * 2 ** attemptRef.current);
      attemptRef.current += 1;
      clearReconnect();
      reconnectTimerRef.current = setTimeout(connect, wait);
    }

    function tearDown(ws) {
      // Detach handlers before closing to keep dev-mode log clean.
      try {
        ws.onopen = null;
        ws.onmessage = null;
        ws.onerror = null;
        ws.onclose = null;
      } catch {
        /* ignore */
      }
      try {
        if (ws.readyState === WebSocket.OPEN) {
          ws.close();
        } else if (ws.readyState === WebSocket.CONNECTING) {
          // Browsers log a noisy "closed before established" warning if we close
          // during CONNECTING. Wait for onopen and close cleanly.
          ws.onopen = () => {
            try {
              ws.close();
            } catch {
              /* ignore */
            }
          };
        }
      } catch {
        /* ignore */
      }
    }

    function connect() {
      if (!activeRef.current) return;
      let ws;
      try {
        ws = new WebSocket(buildWsUrl("/ws/agent"));
      } catch {
        scheduleReconnect();
        return;
      }
      wsRef.current = ws;

      ws.onopen = () => {
        if (!activeRef.current) {
          tearDown(ws);
          return;
        }
        attemptRef.current = 0;
        setConnected(true);
      };

      ws.onmessage = (evt) => {
        let payload;
        try {
          payload = JSON.parse(evt.data);
        } catch {
          return;
        }
        setLastMessageAt(Date.now());
        if (handlerRef.current) {
          try {
            handlerRef.current(payload);
          } catch (err) {
            // Never let a render error tear down the socket
            // eslint-disable-next-line no-console
            console.warn("Finoks WS handler error", err);
          }
        }
      };

      ws.onerror = () => {
        // close fires next; suppress
      };

      ws.onclose = () => {
        setConnected(false);
        if (!activeRef.current) return;
        scheduleReconnect();
      };
    }

    // Defer the real connect by one event-loop tick so React 18 Strict Mode's
    // synchronous double-mount can cancel the timer before a socket is created.
    initialConnectTimer = setTimeout(connect, 0);

    return () => {
      activeRef.current = false;
      if (initialConnectTimer) {
        clearTimeout(initialConnectTimer);
        initialConnectTimer = null;
      }
      clearReconnect();
      const ws = wsRef.current;
      if (ws) {
        tearDown(ws);
      }
      wsRef.current = null;
    };
  }, []);

  return { connected, lastMessageAt };
}
