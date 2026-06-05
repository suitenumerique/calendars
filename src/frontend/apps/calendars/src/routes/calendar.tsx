import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect } from "react";

const CalendarRedirect = () => {
  const navigate = useNavigate();

  useEffect(() => {
    void navigate({ to: "/", replace: true });
  }, [navigate]);

  return null;
};

export const Route = createFileRoute("/calendar")({
  component: CalendarRedirect,
});
