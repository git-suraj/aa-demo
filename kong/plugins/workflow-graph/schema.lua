return {
  name = "workflow-graph",
  fields = {
    {
      protocols = {
        type = "set",
        required = true,
        default = { "http", "https", "grpc", "grpcs" },
        elements = {
          type = "string",
          one_of = { "http", "https", "grpc", "grpcs" },
        },
      },
    },
    {
      config = {
        type = "record",
        fields = {
          {
            include_payloads = {
              type = "boolean",
              required = true,
              default = true,
            },
          },
          {
            payload_max_len = {
              type = "integer",
              required = true,
              default = 4000,
              between = { 0, 20000 },
            },
          },
          {
            export_directly = {
              type = "boolean",
              required = true,
              default = true,
            },
          },
          {
            opik_api_base_url = {
              type = "string",
              required = true,
              default = "http://opik-frontend:5173/api/v1/private",
            },
          },
          {
            project_name = {
              type = "string",
              required = true,
              default = "aa-demo-kong",
            },
          },
          {
            timeout_ms = {
              type = "integer",
              required = true,
              default = 2000,
              between = { 100, 30000 },
            },
          },
          {
            relation_ttl_seconds = {
              type = "integer",
              required = true,
              default = 3600,
              between = { 1, 86400 },
            },
          },
        },
      },
    },
  },
}
