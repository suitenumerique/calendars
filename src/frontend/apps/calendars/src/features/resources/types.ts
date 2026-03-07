export type ResourceType = "ROOM" | "RESOURCE";

export type Resource = {
  id: string;
  name: string;
  email: string;
  resource_type: ResourceType;
  principal_uri: string;
  calendar_uri: string;
};

export type ResourceCreateRequest = {
  name: string;
  resource_type: ResourceType;
};
