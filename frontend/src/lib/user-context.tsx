"use client";

import { createContext, useContext, useState, useEffect, ReactNode } from "react";

export interface SyncedAccount {
  username: string;
  syncedAt: string;
  jobId: string;
  status: "syncing" | "completed" | "failed";
}

export interface UserSession {
  userId: string;
  displayName: string;
  accounts: SyncedAccount[];
  createdAt: string;
}

interface UserContextType {
  user: UserSession | null;
  login: (username: string) => UserSession;
  logout: () => void;
  addAccount: (account: SyncedAccount) => void;
  updateAccountStatus: (username: string, status: SyncedAccount["status"]) => void;
}

const UserContext = createContext<UserContextType | null>(null);

const STORAGE_KEY = "friendly_session";

export function UserProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserSession | null>(null);

  // Hydrate from localStorage on mount
  useEffect(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) setUser(JSON.parse(saved));
    } catch {}
  }, []);

  // Persist to localStorage on change
  useEffect(() => {
    if (user) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(user));
    } else {
      localStorage.removeItem(STORAGE_KEY);
    }
  }, [user]);

  const login = (username: string): UserSession => {
    const session: UserSession = {
      userId: `ig:${username}`,
      displayName: username,
      accounts: [],
      createdAt: new Date().toISOString(),
    };
    setUser(session);
    return session;
  };

  const logout = () => setUser(null);

  const addAccount = (account: SyncedAccount) => {
    setUser((prev) => {
      if (!prev) return prev;
      const existing = prev.accounts.findIndex((a) => a.username === account.username);
      const accounts = [...prev.accounts];
      if (existing >= 0) {
        accounts[existing] = account;
      } else {
        accounts.push(account);
      }
      return { ...prev, accounts };
    });
  };

  const updateAccountStatus = (username: string, status: SyncedAccount["status"]) => {
    setUser((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        accounts: prev.accounts.map((a) =>
          a.username === username ? { ...a, status } : a
        ),
      };
    });
  };

  return (
    <UserContext.Provider value={{ user, login, logout, addAccount, updateAccountStatus }}>
      {children}
    </UserContext.Provider>
  );
}

export function useUser() {
  const ctx = useContext(UserContext);
  if (!ctx) throw new Error("useUser must be used within UserProvider");
  return ctx;
}
