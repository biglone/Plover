declare module "@novnc/novnc" {
  export type RfbCredentials = {
    username?: string;
    password?: string;
    target?: string;
  };

  export type RfbOptions = {
    credentials?: RfbCredentials;
    shared?: boolean;
  };

  export default class RFB {
    constructor(target: HTMLElement, urlOrChannel: string | WebSocket, options?: RfbOptions);

    background: string;
    focusOnClick: boolean;
    resizeSession: boolean;
    scaleViewport: boolean;
    viewOnly: boolean;

    addEventListener(type: string, listener: EventListener): void;
    removeEventListener(type: string, listener: EventListener): void;
    disconnect(): void;
    focus(): void;
    sendCredentials(credentials: RfbCredentials): void;
    sendCtrlAltDel(): void;
  }
}
