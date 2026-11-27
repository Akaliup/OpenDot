import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react';
import { commerce, type CommerceMeta } from './api';

interface CommerceConnection {
  online: boolean | null;
  epoch: number;
}

const CommerceConnectionContext = createContext<CommerceConnection>({
  online: null,
  epoch: 0,
});

export function CommerceConnectionProvider({
  children,
}: {
  children: ReactNode;
}) {
  const [online, setOnline] = useState<boolean | null>(null);
  const [epoch, setEpoch] = useState(0);

  useEffect(() => {
    let stop = false;
    let previous: boolean | null = null;

    async function ping() {
      try {
        const meta = await commerce<CommerceMeta>('/meta');
        if (stop) return;
        const next = meta.online;
        if (previous === false && next) setEpoch((value) => value + 1);
        previous = next;
        setOnline(next);
      } catch {
        if (stop) return;
        previous = false;
        setOnline(false);
      }
    }

    void ping();
    const timer = window.setInterval(() => {
      void ping();
    }, 4000);
    return () => {
      stop = true;
      window.clearInterval(timer);
    };
  }, []);

  return (
    <CommerceConnectionContext.Provider value={{ online, epoch }}>
      {children}
    </CommerceConnectionContext.Provider>
  );
}

export function useCommerceConnection(): CommerceConnection {
  return useContext(CommerceConnectionContext);
}

export function CommerceOfflineBanner() {
  const { online, epoch } = useCommerceConnection();
  if (online === false) {
    return (
      <div
        className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm"
        role="status"
        aria-live="polite"
      >
        <p className="font-medium">CommerceOps 暂时离线</p>
        <p className="mt-1 text-muted-foreground">
          端口 8077
          没有响应。已经保存的草案仍在数据库里，批准按钮已停用。服务恢复后页面会自动刷新，不会把同一笔草案再执行一次。
        </p>
      </div>
    );
  }
  if (online && epoch > 0) {
    return (
      <div
        className="rounded-xl border border-border bg-card/40 p-4 text-sm"
        role="status"
        aria-live="polite"
      >
        <p className="font-medium">CommerceOps 已恢复</p>
        <p className="mt-1 text-muted-foreground">
          草案和审计记录保持原样。待处理草案还是待处理，已执行的草案再次批准只会记下重放。
        </p>
      </div>
    );
  }
  return null;
}
