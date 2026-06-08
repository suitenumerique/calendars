import { Button } from "@gouvfr-lasuite/cunningham-react";
import { ToastContainer, ToastContentProps, toast } from "react-toastify";
import { XMark } from "@gouvfr-lasuite/ui-kit/icons";

export const Toaster = () => {
  return <ToastContainer />;
};

export const ToasterItem = ({
  children,
  closeToast,
  closeButton = false,
  className,
  type = "info",
  onDrop,
}: {
  children: React.ReactNode;
  closeButton?: boolean;
  className?: string;
  type?: "error" | "info" | "success" | "warning";
  onDrop?: (event: React.DragEvent<HTMLDivElement>) => void;
} & Partial<ToastContentProps>) => {
  return (
    <div
      onDrop={(event) => onDrop?.(event)}
      className={["suite__toaster__item", "suite__toaster__item--" + type, className]
        .filter(Boolean)
        .join(" ")}
    >
      <div className="suite__toaster__item__content">{children}</div>
      {closeButton && (
        <Button onClick={closeToast} variant="tertiary" size="small" icon={<XMark />}></Button>
      )}
    </div>
  );
};

export const addToast = (children: React.ReactNode, options: Parameters<typeof toast>[1] = {}) => {
  return toast(children, {
    position: "bottom-center",
    closeButton: false,
    className: "suite__toaster__wrapper",
    autoClose: 8000,
    hideProgressBar: true,
    ...options,
  });
};

export const addErrorToast = (message: string) => {
  return addToast(<ToasterItem type="error">{message}</ToasterItem>);
};

export const addSuccessToast = (message: string) => {
  return addToast(<ToasterItem type="success">{message}</ToasterItem>, {
    autoClose: 4000,
  });
};
