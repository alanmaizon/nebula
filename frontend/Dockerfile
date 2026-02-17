ARG NODE_BASE_IMAGE=public.ecr.aws/docker/library/node:20-alpine
FROM ${NODE_BASE_IMAGE} AS deps

WORKDIR /app

COPY package.json /app/package.json
RUN npm install

FROM ${NODE_BASE_IMAGE} AS builder

WORKDIR /app
COPY --from=deps /app/node_modules /app/node_modules
COPY . /app

ARG NEXT_PUBLIC_API_BASE=/api
ENV NEXT_PUBLIC_API_BASE=${NEXT_PUBLIC_API_BASE}
RUN npm run build

FROM ${NODE_BASE_IMAGE} AS runner

WORKDIR /app
ENV NODE_ENV=production

COPY package.json /app/package.json
COPY --from=deps /app/node_modules /app/node_modules
COPY --from=builder /app/.next /app/.next
COPY --from=builder /app/public /app/public
COPY --from=builder /app/next.config.mjs /app/next.config.mjs

EXPOSE 3000
CMD ["npm", "run", "start", "--", "--hostname", "0.0.0.0", "--port", "3000"]
