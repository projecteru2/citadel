<%inherit file="/base.mako"/>
<%namespace name="utils" file="/utils.mako"/>

<%def name="title()">
  ${ app.name }
</%def>

<%def name="more_css()">
  .block-span { display: block; }
</%def>

<%!
  from datetime import datetime
%>

<%block name="main">

  <%utils:panel>
    <%def name="header()">
      <h3 class="panel-title">App
        <a href="${ url_for('app.app_env', name=app.name) }" class="btn-xs" target="_blank">
          • Environment Variables
        </a>
        <a href="${ url_for('app.app_permitted_users', name=app.name) }" class="btn-xs" target="_blank">
          • Permitted Users
        </a>
        <a href="http://dashboard.ricebook.net/dashboard/db/eru-apps?var-app=${ app.name }" class="btn-xs" target="_blank">
          • 监控
        </a>
      </h3>
    </%def>
    <h4>${ app.name }</h4>
    <p>${ app.gitlab_project.as_dict()['description'] }</p>
    <h5>Log</h5>
    <ul class="list-group">
      % if releases:
        % for entry in releases[0].entrypoints.keys():
          <li class="list-group-item"><a target="_blank" href="${ url_for('app.get_app_log', name=app.name, entrypoint=entry, dt=datetime.now()) }?limit=500">${ entry }</a></li>
        % endfor
      % endif
      <li class="list-group-item">debug log 暂时用 terminal 看：ssh ${ g.user.name }@c2-eru-1.ricebook.link -t 'tail -F /mnt/mfs/logs/heka/debug-output.log -n 100 | ag ${ app.name }'</li>
    </ul>
    <h5>域名</h5>
    <ul class="list-group">
      % for rule in app.get_associated_elb_rules():
        <li class="list-group-item"><a target="_blank" href="${ url_for('loadbalance.elb', name=rule.elbname) }#${ rule.domain }">${ rule.domain }</a></li>
      % endfor
    </ul>
    <button id="delete-app" class="btn btn-warning pull-right" data-appname="${ app.name }"><span class="fui-trash"></span> Delete App</button>
  </%utils:panel>

  <%utils:panel>
    <%def name="header()">
      <h3 class="panel-title">Latest Versions
      </h3>
    </%def>
    ${ utils.release_list(releases, app) }
  </%utils:panel>

  <%utils:panel>
    <%def name="header()">
      <h3 class="panel-title">Online Containers: ${ len(containers) }</h3>
    </%def>
    <%utils:container_list containers="${ containers }">
      <button name="upgrade-all" class="btn btn-primary pull-left" data-toggle="modal" data-target="#upgrade-container-modal"><span class="fui-apple"></span> Upgrade Chosen</button>

    </%utils:container_list>
  </%utils:panel>

  <%call expr="utils.modal('upgrade-container-modal')">
    <%def name="header()">
      <h3 class="modal-title">Upgrade Container</h3>
    </%def>

    <form id="upgrade-container-form" class="form-horizontal" action="">
      <div class="form-group">
        <label class="col-sm-2 control-label" for="">Release</label>
        <div class="col-sm-10">
          <select name="release" class="form-control">
            % for release in releases:
              <option value="${ release.sha }">${ release.short_sha }</option>
            % endfor
          </select>
        </div>
      </div>
    </form>

    <%def name="footer()">
      <button class="btn btn-warning" id="close-modal" data-dismiss="modal"><span class="fui-cross"></span>Close</button>
      <button class="btn btn-info" id="upgrade-container-button"><span class="fui-apple"></span>Upgrade</button>
    </%def>
  </%call>

  <script>

    $('button[id=upgrade-container-button]').click(function(e){
      e.preventDefault();
      if (!$('input[name=container-id]:checked').length) {
        return;
      }

      var payload = [];
      payload.push('sha=' + $('select[name=release]').val());
      payload.push('appname=' + $('h4').html());
      $.each($('input[name=container-id]:checked'), function(){
        payload.push('container_id=' + $(this).val());
      })

      $.post('/ajax/upgrade-container', payload.join('&'), function(){
        location.reload();
      })
    })

    $('button#delete-app').click(function (){
      var self = $(this);
      if (!confirm('确定删除' + self.data('appname') + '?')) { return; }
      $.ajax({
        url: "${ url_for('app.app', name=app.name) }",
        type: 'DELETE',
        success: function(r) {
          console.log(r);
          if (r.status == 200) {
            location.href = "${ url_for('app.index') }";
          }
        },
        error: function(r) {
          console.log(r);
          alert(JSON.stringify(r.responseJSON));
        }
      })
    })
  </script>

</%block>
