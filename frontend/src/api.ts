/**
 * API client for the Job Discovery Engine backend.
 * All requests go through this module for consistent base URL and error handling.
 */
import axios from "axios";

const api = axios.create({
  baseURL: process.env.REACT_APP_API_URL || "http://localhost:8000",
  timeout: 30000, // 30s - search runs can take a while
  headers: {
    "Content-Type": "application/json",
  },
});

// Response interceptor for consistent error handling
api.interceptors.response.use(
  (response) => response,
  (error) => {
    console.error("API Error:", error.response?.data || error.message);
    return Promise.reject(error);
  }
);

export default api;
