/* Deployment access key is entered by the operator, never embedded in assets.
   Keep it in memory only; reload clears it. */
(() => {
  const originalFetch = window.fetch.bind(window);
  const protectedPaths = new Set(['/api/validate', '/api/parse/text', '/api/parse/document']);
  let accessToken = '';
  let askingForToken = false;
  window.fetch = async (input, init = {}) => {
    const url = new URL(input instanceof Request ? input.url : input, location.href);
    if (url.origin !== location.origin || !protectedPaths.has(url.pathname)) {
      return originalFetch(input, init);
    }
    const send = () => {
      const headers = new Headers(init.headers || (input instanceof Request ? input.headers : undefined));
      if (accessToken) headers.set('Authorization', 'Bearer ' + accessToken);
      return originalFetch(input instanceof Request ? input.clone() : input, {...init, headers});
    };
    let response = await send();
    if (response.status === 401 && !askingForToken) {
      askingForToken = true;
      try {
        const entered = window.prompt('이 서비스는 접근 키가 필요합니다. 운영자에게 받은 접근 키를 입력해 주세요.');
        if (entered && entered.trim()) {
          accessToken = entered.trim();
          response = await send();
          if (response.status === 401) accessToken = '';
        }
      } finally {
        askingForToken = false;
      }
    }
    return response;
  };
})();
