"""Comptes et groupes."""

from vivia.configure.client import OpenWebUI


def sync_users(api: OpenWebUI, users: list[dict], groups: list[dict]) -> None:
    known = {u["email"]: u for u in api.call("GET", "/api/v1/users/?page=1")["users"]}
    for user in users:
        if user["email"] not in known:
            payload = {k: v for k, v in user.items() if k != "groups"}
            created = api.try_call("POST", "/api/v1/auths/add", payload | {"profile_image_url": ""})
            if created:
                known[user["email"]] = created
        print(f"  user {user['email']}")

    by_name = {g["name"]: g for g in api.call("GET", "/api/v1/groups/")}
    for group in groups:
        existing = by_name.get(group["name"]) or api.call(
            "POST",
            "/api/v1/groups/create",
            {"name": group["name"], "description": group.get("description", "")},
        )
        members = [
            known[u["email"]]["id"]
            for u in users
            if group["name"] in u.get("groups", []) and u["email"] in known
        ]
        api.try_call(
            "POST",
            f"/api/v1/groups/id/{existing['id']}/update",
            {
                "name": group["name"],
                "description": group.get("description", ""),
                "permissions": group.get("permissions"),
                "user_ids": members,
            },
        )
        print(f"  group {group['name']} ({len(members)} membre(s))")
