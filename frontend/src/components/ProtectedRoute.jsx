import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../context/AuthContext.jsx";

/**
 * Redirect unauthenticated visitors to `/login`; preserve redirect target in state.
 *
 * @param {{ children: import("react").ReactNode }} props
 */
export function ProtectedRoute({ children }) {
  const { token } = useAuth();
  const location = useLocation();

  if (!token) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  return children;
}
