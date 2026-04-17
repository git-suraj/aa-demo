return {
  name = "mcp-trace-enricher",
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
              default = false,
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
        },
      },
    },
  },
}
