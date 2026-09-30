import React from "react";
import ReactDOM from "react-dom/client";
import { ThemeProvider } from "@/context/theme-provider";
import EmployeePortal from "@/pages/EmployeePortal";
import "./index.css";
import "@/utils/i18n";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ThemeProvider defaultTheme="system" storageKey="frigate-employee-theme">
      <EmployeePortal />
    </ThemeProvider>
  </React.StrictMode>,
);
