export const setSessionToken = (token: string) => {
  localStorage.setItem("odoo_migrator_session", token);
};

export const getSessionToken = (): string | null => {
  return localStorage.getItem("odoo_migrator_session");
};

export const removeSessionToken = () => {
  localStorage.removeItem("odoo_migrator_session");
};

// Hook simple para la autenticación
import { useState } from "react";

export const useAuth = () => {
  const [token, setTokenState] = useState<string | null>(getSessionToken());

  const login = (newToken: string) => {
    setSessionToken(newToken);
    setTokenState(newToken);
  };

  const logout = () => {
    removeSessionToken();
    setTokenState(null);
  };

  return { token, login, logout };
};
