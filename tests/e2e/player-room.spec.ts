import { test, expect } from "@playwright/test";

const baseStatus = {
  phase_label: "BRIEFING",
  join_locked: true,
  players: [],
};

const playerSnapshot = {
  ...baseStatus,
  me: {
    player_id: "player-e2e",
    name: "E2E",
    character_id: "char-e2e",
    character_name: "Agent Test",
    envelopes: [],
    role: "killer",
    mission: {
      title: "Mission E2E",
      text: "Valider la reconnection.",
    },
  },
};

test.beforeEach(async ({ context }) => {
  await context.addInitScript(() => {
    window.localStorage.setItem("player_id", "player-e2e");
    window.localStorage.setItem("mp_role", "killer");
    window.localStorage.setItem(
      "mp_mission",
      JSON.stringify({ title: "Mission E2E", text: "Valider la reconnection." })
    );

    class FakeWS {
      static instances: FakeWS[] = [];
      readyState = 1;
      url: string;
      onopen: ((event: Event) => void) | null = null;
      onmessage: ((event: MessageEvent) => void) | null = null;
      onclose: ((event: CloseEvent) => void) | null = null;
      onerror: ((event: Event) => void) | null = null;

      constructor(url: string) {
        this.url = url;
        FakeWS.instances.push(this);
        setTimeout(() => {
          this.onopen?.({} as Event);
        }, 10);
      }

      send() {}

      close() {
        this.readyState = 3;
        this.onclose?.({} as CloseEvent);
      }

      static emit(payload: any) {
        for (const ws of FakeWS.instances) {
          ws.onmessage?.({ data: JSON.stringify(payload) } as MessageEvent);
        }
      }
    }

    // @ts-ignore
    window.WebSocket = FakeWS;
    // @ts-ignore expose for tests
    window.__fakeWS = FakeWS;
  });
});

test("Affichage du rôle et mise à jour mission via WS", async ({ page }) => {
  await page.route("**/game/state*", (route) => {
    const url = new URL(route.request().url());
    if (url.searchParams.has("player_id")) {
      return route.fulfill({ json: playerSnapshot });
    }
    return route.fulfill({ json: baseStatus });
  });

  await page.goto("/room/player-e2e");

  const roleButton = page.getByRole("button", { name: /afficher/i }).first();
  await expect(roleButton).toBeVisible();
  await roleButton.click();
  await expect(page.getByText(/killer/i)).toBeVisible();

  await page.evaluate(() => {
    // @ts-ignore
    window.__fakeWS.emit({
      type: "secret_mission",
      payload: { title: "Brief E2E", text: "Ne partage rien." },
    });
  });

  const missionButton = page.getByRole("button", { name: /afficher/i }).nth(1);
  await missionButton.click();
  await expect(page.getByText("Brief E2E")).toBeVisible();
});
