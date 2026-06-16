import { useState, useContext } from 'react';
import toast from 'react-hot-toast';
import { apiClient } from '../api/client';
import { AuthContext, AuthUser } from '../App';

interface LoginPayload {
  email: string;
  password: string;
}

interface RegisterPayload {
  email: string;
  username: string;
  password: string;
}

interface AuthResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user_id: string;
  email: string;
  is_admin: boolean;
  balance: number;
}

export function useAuthActions() {
  const { setAuth, logout } = useContext(AuthContext);
  const [loading, setLoading] = useState(false);

  const login = async (payload: LoginPayload): Promise<boolean> => {
    setLoading(true);
    try {
      const { data } = await apiClient.post<AuthResponse>('/auth/login', {
        email: payload.email,
        password: payload.password,
      });
      
      const user: AuthUser = {
        id: data.user_id,
        email: data.email,
        username: data.email.split('@')[0],
        is_admin: data.is_admin,
        balance: data.balance,
      };

      setAuth(user, data.access_token);
      toast.success(`Welcome back, ${user.username}!`);
      return true;
    } catch (err: any) {
      const msg = err?.response?.data?.detail || 'Login failed';
      toast.error(msg);
      return false;
    } finally {
      setLoading(false);
    }
  };

  const register = async (payload: RegisterPayload): Promise<boolean> => {
    setLoading(true);
    try {
      const { data } = await apiClient.post<AuthResponse>('/auth/register', {
        email: payload.email,
        password: payload.password,
      });

      const user: AuthUser = {
        id: data.user_id,
        email: data.email,
        username: payload.username || data.email.split('@')[0],
        is_admin: data.is_admin,
        balance: data.balance,
      };

      setAuth(user, data.access_token);
      toast.success('Account created! Welcome to KarmaBhumi.');
      return true;
    } catch (err: any) {
      const msg = err?.response?.data?.detail || 'Registration failed';
      toast.error(msg);
      return false;
    } finally {
      setLoading(false);
    }
  };

  const logoutUser = () => {
    logout();
    toast.success('Logged out successfully');
  };

  return { login, register, logout: logoutUser, loading };
}
